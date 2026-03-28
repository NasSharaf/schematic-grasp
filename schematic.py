"""
Schematic - A next-gen Lisp
Architecture:
    Source text
        ↓ tokenize()
    Token stream
        ↓ parse()
    AST (s-expressions)
        ↓ evaluate()
    Values

Clean separation between each phase.
Future: AST → WASM bytecode
"""

import re
import sys
import os
sys.setrecursionlimit(50000)  # needed for deep map/fold/range operations
from dataclasses import dataclass, field
from typing import Any, Optional

# ─────────────────────────────────────────────
# MODULE REGISTRY
# Tracks loaded .scm files to prevent circular
# requires and avoid redundant loading.
# Maps absolute path → dict of exported names
# ─────────────────────────────────────────────

_loaded_modules: dict = {}   # path → {name: value}
_loading_stack:  list = []   # paths currently being loaded (cycle detection)


# ─────────────────────────────────────────────
# AST NODES
# These are the only things that cross the
# parse/evaluate boundary. Keep them pure data.
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Symbol:
    """An interned symbol. Identity is by name, not object."""
    name: str

    def __repr__(self):
        return self.name

@dataclass(frozen=True)
class Keyword:
    """A self-evaluating keyword, like :red or :ok. Always equal to itself."""
    name: str

    def __repr__(self):
        return f":{self.name}"

@dataclass(frozen=True)
class SList:
    """An immutable linked-list node — the core data structure."""
    head: Any
    tail: Any  # SList or None
    line: int = 0   # source location — 0 means unknown
    col: int = 0

    def __repr__(self):
        items = []
        node = self
        while node is not None:
            items.append(repr(node.head))
            node = node.tail
        return f"({' '.join(items)})"

    def __eq__(self, other):
        if not isinstance(other, SList):
            return False
        return self.head == other.head and self.tail == other.tail

    def __hash__(self):
        return hash((self.head, self.tail))

    def to_python_list(self):
        result = []
        node = self
        while node is not None:
            result.append(node.head)
            node = node.tail
        return result

@dataclass(frozen=True)
class Vector:
    """Immutable vector, like Clojure's []."""
    items: tuple

    def __repr__(self):
        return f"[{' '.join(repr(i) for i in self.items)}]"

@dataclass(frozen=True)
class SchematicMap:
    """Immutable hash map."""
    pairs: tuple  # tuple of (key, value) pairs

    def to_dict(self):
        return dict(self.pairs)

    def __repr__(self):
        inner = ' '.join(f"{repr(k)} {repr(v)}" for k, v in self.pairs)
        return "{" + inner + "}"

# Sentinel values
NIL = None
TRUE = True
FALSE = False


# ─────────────────────────────────────────────
# TOKENIZER
# ─────────────────────────────────────────────

@dataclass
class Token:
    kind: str   # LPAREN RPAREN LBRACKET RBRACKET LBRACE RBRACE
                # SYMBOL KEYWORD NUMBER STRING QUOTE INDENT DEDENT NEWLINE
    value: Any
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"

class LexError(Exception):
    pass

def tokenize(source: str) -> list[Token]:
    """
    Tokenize Schematic source, handling sweet expressions.
    Sweet expression rules:
      - Indentation only matters at the TOP LEVEL (depth 0)
      - Inside parens, normal s-expression rules apply
      - f(x, y) is neoteric sugar for (f x y)
      - Blank lines and comment-only lines are skipped
    """
    tokens = []
    lines = source.splitlines()
    indent_stack = [0]
    paren_depth = 0  # track open parens — inside parens, ignore indentation

    for lineno, raw_line in enumerate(lines, 1):
        stripped = raw_line.lstrip()
        if not stripped or stripped.startswith(';'):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())

        # Only emit INDENT/DEDENT at top level (not inside parens)
        if paren_depth == 0:
            if indent > indent_stack[-1]:
                indent_stack.append(indent)
                tokens.append(Token('INDENT', indent, lineno, 0))
            else:
                while indent < indent_stack[-1]:
                    indent_stack.pop()
                    tokens.append(Token('DEDENT', indent, lineno, 0))
                if indent != indent_stack[-1]:
                    raise LexError(f"Line {lineno}: inconsistent indentation")
            tokens.append(Token('NEWLINE', None, lineno, 0))
        else:
            # Inside parens: emit a SPACE to prevent cross-line neoteric calls
            # e.g. (match n\n  (0 => x)) should NOT parse as (match n(0 => x))
            tokens.append(Token('SPACE', None, lineno, 0))

        line_tokens = _tokenize_line(stripped, lineno)

        # Track paren depth across the line
        for tok in line_tokens:
            if tok.kind in ('LPAREN', 'LBRACKET', 'LBRACE'):
                paren_depth += 1
            elif tok.kind in ('RPAREN', 'RBRACKET', 'RBRACE'):
                paren_depth -= 1

        tokens.extend(line_tokens)

    # Close any remaining indentation
    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token('DEDENT', 0, len(lines), 0))

    return tokens


def _tokenize_line(line: str, lineno: int) -> list[Token]:
    """Tokenize a single line into tokens."""
    tokens = []
    i = 0

    TOKEN_RE = re.compile(r"""
        (?P<COMMENT>  ;.* )                          |
        (?P<STRING>   "(?:[^"\\]|\\.)*" )            |
        (?P<NUMBER>   -?(?:\d+\.\d*|\d+) )           |
        (?P<KEYWORD>  :[a-zA-Z_][a-zA-Z0-9_\-?!]* ) |
        (?P<LPAREN>   \( )                           |
        (?P<RPAREN>   \) )                           |
        (?P<LBRACKET> \[ )                           |
        (?P<RBRACKET> \] )                           |
        (?P<LBRACE>   \{ )                           |
        (?P<RBRACE>   \} )                           |
        (?P<QUOTE>    ' )                            |
        (?P<UNQUOTE_SPLICE> ,@ )                     |
        (?P<UNQUOTE>  , )                            |
        (?P<QUASI>    ` )                            |
        (?P<DOT>      (?<!\d)\.(?!\d) )             |
        (?P<LAMBDA_SYM> \u03bb )                     |
        (?P<BACK_EDGE>  \u00bf[a-zA-Z_][a-zA-Z0-9_\-?!]* ) |
        (?P<SYMBOL>   [a-zA-Z_+\-*/<>=!?][a-zA-Z0-9_+\-*/<>=!?.]* ) |
        (?P<SPACE>    \s+ )
    """, re.VERBOSE)

    for m in TOKEN_RE.finditer(line):
        kind = m.lastgroup
        val = m.group()
        col = m.start()

        if kind == 'COMMENT' or kind == 'SPACE':
            # Track that a space occurred - breaks neoteric calls
            if kind == 'SPACE':
                tokens.append(Token('SPACE', None, lineno, col))
            continue
        elif kind == 'NUMBER':
            val = float(val) if '.' in val else int(val)
        elif kind == 'STRING':
            val = val[1:-1].encode().decode('unicode_escape')
        elif kind == 'KEYWORD':
            val = val[1:]  # strip leading :
            tokens.append(Token('KEYWORD', val, lineno, col))
            continue
        elif kind == 'DOT':
            tokens.append(Token('SYMBOL', '.', lineno, col))
            continue
        elif kind == 'QUASI':
            tokens.append(Token('QUASI', '`', lineno, col))
            continue
        elif kind == 'UNQUOTE':
            tokens.append(Token('UNQUOTE', ',', lineno, col))
            continue
        elif kind == 'UNQUOTE_SPLICE':
            tokens.append(Token('UNQUOTE_SPLICE', ',@', lineno, col))
            continue
        elif kind == 'LAMBDA_SYM':
            # λ is an alias for lambda
            tokens.append(Token('SYMBOL', 'lambda', lineno, col))
            continue
        elif kind == 'BACK_EDGE':
            # ¿name — the back-edge operator, emit as symbol '?back-name'
            # Strip the ¿ prefix, emit as (?back name) sugar
            # For now emit as a plain symbol so grasp-read handles it
            tokens.append(Token('SYMBOL', val, lineno, col))
            continue

        tokens.append(Token(kind, val, lineno, col))

    return tokens


# ─────────────────────────────────────────────
# PARSER
# Converts token stream → AST (nested SList/Symbol/etc)
# Handles both classic s-expressions AND sweet expressions
# ─────────────────────────────────────────────

class ParseError(Exception):
    pass

class Parser:
    def __init__(self, tokens: list[Token], sweet: bool = True):
        self.tokens = [t for t in tokens if t.kind not in ('NEWLINE',)] if not sweet else tokens
        self.pos = 0
        self.sweet = sweet

    def peek(self) -> Optional[Token]:
        # Skip structural tokens when peeking for values
        while self.pos < len(self.tokens) and self.tokens[self.pos].kind in ('INDENT', 'DEDENT', 'SPACE'):
            self.pos += 1
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def peek_raw(self) -> Optional[Token]:
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def next_is_immediate_lparen(self) -> bool:
        """True if the very next token (no space) is LPAREN — neoteric call."""
        if self.pos >= len(self.tokens):
            return False
        next_tok = self.tokens[self.pos]
        return next_tok.kind == 'LPAREN'

    def consume(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.peek()
        if tok is None or tok.kind != kind:
            got = repr(tok) if tok else 'EOF'
            raise ParseError(f"Expected {kind}, got {got}")
        return self.consume()

    def parse_all(self) -> list:
        """Parse all top-level expressions, respecting sweet expression grouping."""
        exprs = []
        if self.sweet:
            while self.peek() is not None:
                e = self.parse_sweet()
                if e is not None:
                    exprs.append(e)
        else:
            while self.peek() is not None:
                exprs.append(self.parse_expr())
        return exprs

    def parse_sweet(self) -> Any:
        """
        Parse one sweet expression.

        Rules:
          - A line starting with ( is a classic s-expression, stands alone
          - A line starting with a bare symbol collects the whole line as one form
          - If followed by INDENT, indented lines become additional tail arguments

        Examples:
          define factorial(n)     <- bare symbol head, collects whole line
            (match n ...)         <- indented body arg

          (define x 10)           <- classic paren form, stands alone
        """
        # Consume leading NEWLINEs and SPACEs
        while self.peek_raw() and self.peek_raw().kind in ('NEWLINE', 'SPACE'):
            self.consume()

        if self.peek() is None:
            return None

        # If the line starts with a paren/bracket/brace/quote, parse ONE classic form
        raw = self.peek_raw()
        if raw and raw.kind in ('LPAREN', 'LBRACKET', 'LBRACE', 'QUOTE'):
            expr = self.parse_expr()
            while self.peek_raw() and self.peek_raw().kind in ('SPACE',):
                self.consume()
            return expr

        # Otherwise: bare symbol or neoteric — collect the whole line
        line_items = []
        while True:
            raw = self.peek_raw()
            if raw is None or raw.kind in ('NEWLINE', 'INDENT', 'DEDENT'):
                break
            if raw.kind == 'SPACE':
                self.consume()
                continue
            line_items.append(self.parse_expr())

        # Special case: if line is (lambda (params)) body...
        # rewrite as (lambda (params) body...) — merge body into lambda
        if (len(line_items) >= 2
                and isinstance(line_items[0], SList)
                and isinstance(line_items[0].head, Symbol)
                and line_items[0].head.name == 'lambda'):
            lam_parts = slist_to_python(line_items[0])  # [lambda, (params)]
            body_items = line_items[1:]
            line_items = [python_list_to_slist(lam_parts + body_items)]

        # Consume trailing NEWLINE
        while self.peek_raw() and self.peek_raw().kind == 'NEWLINE':
            self.consume()

        # If next is INDENT, indented block provides more arguments
        indent_args = []
        if self.peek_raw() and self.peek_raw().kind == 'INDENT':
            self.consume()  # consume INDENT
            while True:
                while self.peek_raw() and self.peek_raw().kind == 'NEWLINE':
                    self.consume()
                if self.peek_raw() is None or self.peek_raw().kind == 'DEDENT':
                    break
                sub = self.parse_sweet()
                if sub is not None:
                    indent_args.append(sub)
            if self.peek_raw() and self.peek_raw().kind == 'DEDENT':
                self.consume()

        all_items = line_items + indent_args

        if len(all_items) == 0:
            return None
        if len(all_items) == 1:
            return all_items[0]
        return python_list_to_slist(all_items)


    def parse_expr(self) -> Any:
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected EOF")

        if tok.kind == 'QUOTE':
            self.consume()
            inner = self.parse_expr()
            return python_list_to_slist([Symbol('quote'), inner])

        if tok.kind == 'QUASI':
            self.consume()
            inner = self.parse_expr()
            return python_list_to_slist([Symbol('quasiquote'), inner])

        if tok.kind == 'UNQUOTE_SPLICE':
            self.consume()
            inner = self.parse_expr()
            return python_list_to_slist([Symbol('unquote-splicing'), inner])

        if tok.kind == 'UNQUOTE':
            self.consume()
            inner = self.parse_expr()
            return python_list_to_slist([Symbol('unquote'), inner])

        if tok.kind == 'LPAREN':
            return self.parse_sexp_list()

        if tok.kind == 'LBRACKET':
            return self.parse_vector()

        if tok.kind == 'LBRACE':
            return self.parse_map()

        if tok.kind == 'SYMBOL':
            self.consume()
            sym = Symbol(tok.value)
            # Neoteric: f(x, y) only if LPAREN immediately follows with NO space
            if self.next_is_immediate_lparen():
                args = self.parse_neoteric_args()
                # Special case: lambda(params...) → (lambda (params...) ...)
                # wrap args in a list so they read as a param list
                if sym.name == 'lambda' and args:
                    wrapped = python_list_to_slist(args)
                    return python_list_to_slist([sym, wrapped])
                items = [sym] + args
                return python_list_to_slist(items)
            return sym

        if tok.kind == 'KEYWORD':
            self.consume()
            return Keyword(tok.value)

        if tok.kind == 'NUMBER':
            self.consume()
            return tok.value

        if tok.kind == 'STRING':
            self.consume()
            return tok.value

        raise ParseError(f"Unexpected token: {tok}")

    def parse_sexp_list(self) -> SList:
        """Parse a classic (a b c) list."""
        open_tok = self.expect('LPAREN')
        line, col = open_tok.line, open_tok.col
        items = []
        while True:
            tok = self.peek()
            if tok is None:
                raise ParseError("Unterminated list")
            if tok.kind == 'RPAREN':
                self.consume()
                break
            items.append(self.parse_expr())
        return python_list_to_slist(items, line, col)

    def parse_neoteric_args(self) -> list:
        """Parse f(x, y) argument list → [x, y]
        Handles lambda(params) body within args."""
        self.expect('LPAREN')
        args = []
        while True:
            tok = self.peek()
            if tok is None:
                raise ParseError("Unterminated argument list")
            if tok.kind == 'RPAREN':
                self.consume()
                break
            # Skip commas
            raw = self.peek_raw()
            if raw and raw.kind == 'SYMBOL' and raw.value == ',':
                self.consume()
                continue
            if raw and raw.kind == 'SPACE':
                self.consume()
                continue
            expr = self.parse_expr()
            # If we just parsed (lambda (params)) with no body,
            # grab the next non-comma expression as its body
            if (isinstance(expr, SList)
                    and isinstance(expr.head, Symbol)
                    and expr.head.name == 'lambda'):
                parts = slist_to_python(expr)
                # (lambda (params)) has exactly 2 parts — missing body
                if len(parts) == 2:
                    # skip space/comma
                    while self.peek_raw() and self.peek_raw().kind in ('SPACE',):
                        self.consume()
                    raw2 = self.peek_raw()
                    if raw2 and raw2.kind not in ('RPAREN', 'COMMA') and raw2.value != ',':
                        body = self.parse_expr()
                        expr = python_list_to_slist(parts + [body])
            args.append(expr)
        return args

    def parse_vector(self) -> Vector:
        self.expect('LBRACKET')
        items = []
        while True:
            tok = self.peek()
            if tok is None:
                raise ParseError("Unterminated vector")
            if tok.kind == 'RBRACKET':
                self.consume()
                break
            items.append(self.parse_expr())
        return Vector(tuple(items))

    def parse_map(self) -> SchematicMap:
        self.expect('LBRACE')
        pairs = []
        while True:
            tok = self.peek()
            if tok is None:
                raise ParseError("Unterminated map")
            if tok.kind == 'RBRACE':
                self.consume()
                break
            k = self.parse_expr()
            v = self.parse_expr()
            pairs.append((k, v))
        return SchematicMap(tuple(pairs))


def parse(source: str, sweet: bool = True) -> list:
    """Full pipeline: source → list of AST nodes.
    sweet=True: use sweet expression grouping (default for user code)
    sweet=False: classic s-expression parsing (used for prelude)
    """
    tokens = tokenize(source)
    parser = Parser(tokens, sweet=sweet)
    return parser.parse_all()


def python_list_to_slist(items: list, line: int = 0, col: int = 0) -> Any:
    """Convert a Python list to an SList (or None for empty)."""
    result = None
    for item in reversed(items):
        result = SList(item, result, line, col)
    return result


def slist_to_python(slist) -> list:
    """Convert SList to Python list."""
    if slist is None:
        return []
    return slist.to_python_list()


# ─────────────────────────────────────────────
# ENVIRONMENT
# Lexical scoping via chained environments
# ─────────────────────────────────────────────

class Environment:
    def __init__(self, bindings: dict = None, parent: 'Environment' = None):
        self.bindings = bindings or {}
        self.parent = parent

    def lookup(self, name: str) -> Any:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        raise SchematicError(f"Undefined symbol: {name}")

    def define(self, name: str, value: Any):
        self.bindings[name] = value

    def extend(self, names: list, values: list) -> 'Environment':
        return Environment(dict(zip(names, values)), parent=self)


# ─────────────────────────────────────────────
# VALUES
# ─────────────────────────────────────────────

@dataclass
class Lambda:
    """A user-defined function with its closure environment."""
    params: list      # list of str
    body: list        # list of AST nodes (implicit begin)
    env: Environment
    name: str = None  # optional, for display

    def __repr__(self):
        name = self.name or 'λ'
        return f"#<lambda:{name}({', '.join(self.params)})>"

@dataclass
class Macro:
    """A hygienic macro — receives unevaluated AST, returns transformed AST."""
    params: list
    body: list
    env: Environment
    name: str = None

    def __repr__(self):
        return f"#<macro:{self.name or '?'}>"

@dataclass
class Builtin:
    """A built-in function implemented in Python."""
    name: str
    fn: Any

    def __repr__(self):
        return f"#<builtin:{self.name}>"

class SchematicError(Exception):
    """Runtime error with optional source location."""
    def __init__(self, message: str, line: int = None, col: int = None, source_line: str = None):
        self.message = message
        self.line = line
        self.col = col
        self.source_line = source_line
        super().__init__(self._format())

    def _format(self):
        if self.line:
            loc = f"line {self.line}"
            if self.col:
                loc += f", col {self.col}"
            if self.source_line:
                return f"{loc}: {self.message}\n  {self.source_line.rstrip()}"
            return f"{loc}: {self.message}"
        return self.message

    def with_location(self, line, col=None, source_line=None):
        """Return a new error enriched with location if not already set."""
        if self.line is not None:
            return self
        return SchematicError(self.message, line, col, source_line)


class TailCall:
    """Trampoline marker for tail call optimization."""
    __slots__ = ['fn', 'args']
    def __init__(self, fn, args):
        self.fn = fn
        self.args = args


    """Trampoline marker for tail call optimization."""
    __slots__ = ['fn', 'args']
    def __init__(self, fn, args):
        self.fn = fn
        self.args = args


# ─────────────────────────────────────────────
# QUASIQUOTE EXPANDER
# Handles: `(a ,b ,@c d)
# In Schematic syntax: (quasiquote (a (unquote b) (unquote-splicing c) d))
# ─────────────────────────────────────────────

def _expand_quasiquote(template, env) -> Any:
    """
    Recursively expand a quasiquote template.

    Rules:
      atom            -> return as-is (like quote)
      (unquote x)     -> evaluate x and return the value
      (unquote-splicing x) -> only valid inside a list, splices items in
      (a b c ...)     -> recursively expand each element,
                         splicing unquote-splicing where found
    """
    # Atoms pass through unchanged
    if not isinstance(template, SList):
        return template

    items = slist_to_python(template)

    # (unquote expr) — evaluate and return
    if items and isinstance(items[0], Symbol) and items[0].name == 'unquote':
        return evaluate(items[1], env)

    # It's a list — walk each element, watching for unquote-splicing
    result = []
    for item in items:
        if isinstance(item, SList):
            sub = slist_to_python(item)
            if sub and isinstance(sub[0], Symbol) and sub[0].name == 'unquote-splicing':
                # Evaluate and splice the list in
                spliced = evaluate(sub[1], env)
                result.extend(slist_to_python(spliced))
                continue
        result.append(_expand_quasiquote(item, env))

    return python_list_to_slist(result)


# ─────────────────────────────────────────────
# PATTERN MATCHING  (upgraded)
#
# Supported patterns:
#   _                wildcard
#   42  "str"  :kw   literal match
#   true false nil   literal booleans/nil
#   x                bind to variable x
#   (p1 p2 p3)       fixed-length list destructure
#   (p1 p2 . rest)   list with rest binding
#   [p1 p2]          vector destructure
#   (? pred)         guard — matches if (pred value) is truthy
#   (and p1 p2)      match both patterns (bind from both)
#   (or p1 p2)       match either pattern (first wins)
# ─────────────────────────────────────────────

def match_pattern(pattern, value, bindings: dict, env=None) -> bool:
    """
    Try to match value against pattern.
    Fills bindings dict on success. Returns True/False.
    env is needed for guard patterns (? pred).
    """
    # Wildcard
    if isinstance(pattern, Symbol) and pattern.name == '_':
        return True

    # Literal boolean/nil keywords
    if isinstance(pattern, Symbol) and pattern.name == 'true':
        return value is True
    if isinstance(pattern, Symbol) and pattern.name == 'false':
        return value is False or value is None
    if isinstance(pattern, Symbol) and pattern.name == 'nil':
        return value is None

    # Literal number or string
    if isinstance(pattern, (int, float, str)):
        return pattern == value

    # Keyword literal
    if isinstance(pattern, Keyword):
        return isinstance(value, Keyword) and value.name == pattern.name

    # Plain symbol — bind it
    if isinstance(pattern, Symbol):
        bindings[pattern.name] = value
        return True

    # List pattern
    if isinstance(pattern, SList):
        pat_items = slist_to_python(pattern)
        if not pat_items:
            return value is None

        head = pat_items[0]

        # (? predicate) — guard pattern
        if isinstance(head, Symbol) and head.name == '?':
            if env is None:
                raise SchematicError("guard pattern requires env")
            pred = evaluate(pat_items[1], env)
            result = _apply(pred, [value])
            return result is not False and result is not None

        # (and p1 p2 ...) — all patterns must match, bindings accumulate
        if isinstance(head, Symbol) and head.name == 'and':
            for p in pat_items[1:]:
                if not match_pattern(p, value, bindings, env):
                    return False
            return True

        # (or p1 p2 ...) — first matching pattern wins
        if isinstance(head, Symbol) and head.name == 'or':
            for p in pat_items[1:]:
                b = {}
                if match_pattern(p, value, b, env):
                    bindings.update(b)
                    return True
            return False

        # (p1 p2 . rest) — dotted list with rest
        # We represent this as a plain list where second-to-last is '.'
        if len(pat_items) >= 3 and isinstance(pat_items[-2], Symbol) and pat_items[-2].name == '.':
            # (p1 p2 . rest) — match fixed prefix, bind rest
            fixed = pat_items[:-2]
            rest_sym = pat_items[-1]
            val_items = slist_to_python(value) if isinstance(value, SList) else []
            if value is None:
                val_items = []
            if len(val_items) < len(fixed):
                return False
            for p, v in zip(fixed, val_items):
                if not match_pattern(p, v, bindings, env):
                    return False
            # bind rest to remainder as a list
            rest_val = python_list_to_slist(val_items[len(fixed):])
            if isinstance(rest_sym, Symbol):
                bindings[rest_sym.name] = rest_val
            return True

        # Fixed-length list destructure
        if not isinstance(value, SList) and value is not None:
            return False
        val_items = slist_to_python(value) if isinstance(value, SList) else []
        if len(pat_items) != len(val_items):
            return False
        for p, v in zip(pat_items, val_items):
            if not match_pattern(p, v, bindings, env):
                return False
        return True

    # Vector pattern
    if isinstance(pattern, Vector):
        if not isinstance(value, Vector):
            return False
        if len(pattern.items) != len(value.items):
            return False
        for p, v in zip(pattern.items, value.items):
            if not match_pattern(p, v, bindings, env):
                return False
        return True

    return False


def _parse_match_clauses(items: list) -> list:
    """
    Parse a sequence of match clause items into (pattern, guard, body) triples.

    Handles three formats:
      (pat => body)           -- wrapped: one SList item
      pat => body             -- flat: individual items
      (list-pat) => body      -- list pattern with flat arrow

    Also handles 'when' guards:
      (pat when guard => body)
      pat when guard => body
    """
    clauses = []

    # First, flatten wrapped clauses into a single stream.
    # A wrapped clause is an SList whose items contain '=>'.
    # We detect this by checking if an item is an SList containing '=>'.
    stream = []
    for item in items:
        if isinstance(item, SList):
            sub = slist_to_python(item)
            has_arrow = any(
                isinstance(x, Symbol) and x.name == '=>' for x in sub
            )
            if has_arrow:
                # Wrapped clause — flatten into stream
                stream.extend(sub)
                stream.append(None)  # clause boundary marker
            else:
                # It's a list-pattern in a flat clause
                stream.append(item)
        else:
            stream.append(item)

    # Now parse stream into clauses, splitting on None (boundary) or '=>'
    i = 0
    while i < len(stream):
        # Skip boundary markers
        if stream[i] is None:
            i += 1
            continue

        # Collect tokens until we find '=>'
        before = []
        while i < len(stream) and not (
            isinstance(stream[i], Symbol) and stream[i].name == '=>'
        ) and stream[i] is not None:
            before.append(stream[i])
            i += 1

        if i >= len(stream) or stream[i] is None:
            # No arrow found — skip
            i += 1
            continue

        i += 1  # consume '=>'

        # Next non-None item is body
        body = stream[i] if i < len(stream) else None
        i += 1

        # Skip boundary marker after body
        if i < len(stream) and stream[i] is None:
            i += 1

        # Parse before into (pattern, guard)
        when_idx = next(
            (j for j, x in enumerate(before)
             if isinstance(x, Symbol) and x.name == 'when'),
            None
        )

        if when_idx is not None:
            pat_items = before[:when_idx]
            guard = before[when_idx + 1] if when_idx + 1 < len(before) else None
        else:
            pat_items = before
            guard = None

        # Wrap multi-item patterns back into a list
        if len(pat_items) == 0:
            pattern = None
        elif len(pat_items) == 1:
            pattern = pat_items[0]
            # Check if single list pattern contains 'when' inside it:
            # e.g. (:node v l r when (< val v))
            if isinstance(pattern, SList) and guard is None:
                inner = slist_to_python(pattern)
                inner_when = next(
                    (j for j, x in enumerate(inner)
                     if isinstance(x, Symbol) and x.name == 'when'),
                    None
                )
                if inner_when is not None:
                    guard = inner[inner_when + 1] if inner_when + 1 < len(inner) else None
                    pattern = python_list_to_slist(inner[:inner_when])
        else:
            pattern = python_list_to_slist(pat_items)

        clauses.append((pattern, guard, body))

    return clauses






def evaluate(ast, env: Environment) -> Any:
    """
    Evaluate an AST node in an environment.
    Uses a trampoline loop for tail call optimization.
    Enriches errors with source location when available.
    """
    while True:
        try:
            result = _eval_step(ast, env)
        except SchematicError as e:
            # Enrich with location from the AST node if available
            if isinstance(ast, SList) and ast.line:
                raise e.with_location(ast.line, ast.col) from None
            raise
        except Exception as e:
            # Wrap unexpected Python errors
            msg = str(e) or type(e).__name__
            if isinstance(ast, SList) and ast.line:
                raise SchematicError(f"Internal: {msg}", ast.line, ast.col) from e
            raise SchematicError(f"Internal: {msg}") from e

        if isinstance(result, TailCall):
            fn = result.fn
            args = result.args
            if isinstance(fn, Lambda):
                if len(args) != len(fn.params):
                    err = SchematicError(
                        f"Arity mismatch: {fn.name or 'λ'} expects "
                        f"{len(fn.params)} args, got {len(args)}"
                    )
                    if isinstance(ast, SList) and ast.line:
                        raise err.with_location(ast.line, ast.col)
                    raise err
                env = fn.env.extend(fn.params, args)
                for expr in fn.body[:-1]:
                    evaluate(expr, env)
                ast = fn.body[-1]
                continue
            elif callable(fn):
                return fn(*args)
            else:
                raise SchematicError(f"Not callable: {fn!r}")
        return result


def _eval_step(ast, env: Environment) -> Any:
    """One evaluation step. May return a TailCall."""

    # Self-evaluating atoms
    if ast is None:
        return None
    if isinstance(ast, (int, float, str, bool)):
        return ast
    if isinstance(ast, Keyword):
        return ast
    if isinstance(ast, Vector):
        return Vector(tuple(evaluate(item, env) for item in ast.items))
    if isinstance(ast, SchematicMap):
        return SchematicMap(tuple(
            (evaluate(k, env), evaluate(v, env))
            for k, v in ast.pairs
        ))

    # Symbol lookup
    if isinstance(ast, Symbol):
        return env.lookup(ast.name)

    # List — special forms and function application
    if isinstance(ast, SList):
        items = slist_to_python(ast)
        if not items:
            return None

        head = items[0]
        rest = items[1:]

        # ── Special forms ──────────────────────────────

        # (quote x)
        if isinstance(head, Symbol) and head.name == 'quote':
            return rest[0]

        # (quasiquote x) -- backtick template
        if isinstance(head, Symbol) and head.name == 'quasiquote':
            return _expand_quasiquote(rest[0], env)

        # unquote at top level is an error
        if isinstance(head, Symbol) and head.name == 'unquote':
            raise SchematicError("unquote outside of quasiquote")

        # (if condition then else?)
        if isinstance(head, Symbol) and head.name == 'if':
            condition = evaluate(rest[0], env)
            if condition is not False and condition is not None:
                return _eval_step(rest[1], env)
            elif len(rest) > 2:
                return _eval_step(rest[2], env)
            return None

        # (define name value) or (define (name params...) body...)
        if isinstance(head, Symbol) and head.name == 'define':
            if isinstance(rest[0], Symbol):
                # (define x expr)
                val = evaluate(rest[1], env)
                if isinstance(val, Lambda) and val.name is None:
                    val = Lambda(val.params, val.body, val.env, name=rest[0].name)
                env.define(rest[0].name, val)
                return None
            elif isinstance(rest[0], SList):
                # (define (f x y) body...)
                name_and_params = slist_to_python(rest[0])
                fname = name_and_params[0].name
                params = [p.name for p in name_and_params[1:]]
                body = rest[1:]
                lam = Lambda(params, body, env, name=fname)
                env.define(fname, lam)
                return None

        # (lambda (params...) body...)
        # Also handles neoteric: lambda(x) body → (lambda x body)
        if isinstance(head, Symbol) and head.name == 'lambda':
            param_spec = rest[0]
            if isinstance(param_spec, Symbol):
                # neoteric lambda(x) or lambda(x y) — single symbol or already a list
                params = [param_spec.name]
            elif isinstance(param_spec, SList):
                params = [p.name for p in slist_to_python(param_spec)]
            else:
                params = []
            body = rest[1:]
            return Lambda(params, body, env)

        # (let ((x v) ...) body...)
        if isinstance(head, Symbol) and head.name == 'let':
            bindings_list = slist_to_python(rest[0])
            child_env = Environment(parent=env)
            for binding in bindings_list:
                b = slist_to_python(binding)
                child_env.define(b[0].name, evaluate(b[1], env))
            for expr in rest[1:-1]:
                evaluate(expr, child_env)
            return _eval_step(rest[-1], child_env)

        # (let* ((x v) ...) body...) — sequential bindings
        if isinstance(head, Symbol) and head.name == 'let*':
            bindings_list = slist_to_python(rest[0])
            child_env = Environment(parent=env)
            for binding in bindings_list:
                b = slist_to_python(binding)
                child_env.define(b[0].name, evaluate(b[1], child_env))
            for expr in rest[1:-1]:
                evaluate(expr, child_env)
            return _eval_step(rest[-1], child_env)

        # (begin expr...)
        if isinstance(head, Symbol) and head.name == 'begin':
            if not rest:
                return None
            for expr in rest[:-1]:
                evaluate(expr, env)
            return _eval_step(rest[-1], env)

        # (cond (test expr)... (else expr))
        if isinstance(head, Symbol) and head.name == 'cond':
            for clause in rest:
                c = slist_to_python(clause)
                if isinstance(c[0], Symbol) and c[0].name == 'else':
                    return _eval_step(c[1], env)
                if evaluate(c[0], env) is not False and evaluate(c[0], env) is not None:
                    return _eval_step(c[1], env)
            return None

        # (and expr...)
        if isinstance(head, Symbol) and head.name == 'and':
            result = True
            for expr in rest:
                result = evaluate(expr, env)
                if result is False or result is None:
                    return False
            return result

        # (or expr...)
        if isinstance(head, Symbol) and head.name == 'or':
            for expr in rest:
                result = evaluate(expr, env)
                if result is not False and result is not None:
                    return result
            return False

        # (match expr clause...)
        # Handles three clause formats uniformly by scanning for '=>':
        #   (pat => body)           -- wrapped clause
        #   pat => body             -- flat clause  
        #   (list-pat) => body      -- list pattern, flat arrow
        # Also supports 'when' guards anywhere before '=>'
        if isinstance(head, Symbol) and head.name == 'match':
            value = evaluate(rest[0], env)
            clauses = _parse_match_clauses(rest[1:])
            for pattern, guard, body_expr in clauses:
                bindings = {}
                if match_pattern(pattern, value, bindings, env):
                    match_env = Environment(bindings, parent=env)
                    if guard is not None:
                        guard_result = evaluate(guard, match_env)
                        if guard_result is False or guard_result is None:
                            continue
                    return _eval_step(body_expr, match_env)
            raise SchematicError(f"No matching pattern for: {value!r}")

        # (define-macro (name params...) body...)
        if isinstance(head, Symbol) and head.name == 'define-macro':
            name_and_params = slist_to_python(rest[0])
            mname = name_and_params[0].name
            params = [p.name for p in name_and_params[1:]]
            body = rest[1:]
            macro = Macro(params, body, env, name=mname)
            env.define(mname, macro)
            return None

        # (import "module")            → import and return module
        # (import "module" :as :name)  → import and bind as name in current env
        # (import "module" :as name)   → same with symbol name
        if isinstance(head, Symbol) and head.name == 'import':
            import importlib
            module_name = evaluate(rest[0], env)
            if not isinstance(module_name, str):
                raise SchematicError(f"import: module name must be a string, got {module_name!r}")
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                raise SchematicError(f"import: {e}")
            # Handle :as alias
            if len(rest) >= 3:
                as_kw = rest[1]
                alias_node = rest[2]
                if isinstance(as_kw, Keyword) and as_kw.name == 'as':
                    alias = alias_node.name if isinstance(alias_node, (Symbol, Keyword)) else str(alias_node)
                    env.define(alias, mod)
            return mod

        # (require "file.scm")
        # Load a Schematic file and import all provided names
        # into the current environment. Circular detection prevents
        # infinite loops. Second require of same file is a no-op.
        if isinstance(head, Symbol) and head.name == 'require':
            raw_path = evaluate(rest[0], env)
            if not isinstance(raw_path, str):
                raise SchematicError(f"require: path must be a string, got {raw_path!r}")

            # Resolve path relative to the requiring file's directory
            current_file = env.lookup('__file__') if '__file__' in _get_all_names(env) else None
            if current_file and not os.path.isabs(raw_path):
                base_dir = os.path.dirname(current_file)
                abs_path = os.path.normpath(os.path.join(base_dir, raw_path))
            else:
                abs_path = os.path.normpath(os.path.abspath(raw_path))

            # Already loaded — just re-import exports into current env
            if abs_path in _loaded_modules:
                for name, val in _loaded_modules[abs_path].items():
                    env.define(name, val)
                return None

            # Circular require detection
            if abs_path in _loading_stack:
                raise SchematicError(f"require: circular dependency detected: {abs_path}")

            # Load the file
            if not os.path.exists(abs_path):
                raise SchematicError(f"require: file not found: {abs_path}")

            try:
                with open(abs_path) as f:
                    source = f.read()
            except OSError as e:
                raise SchematicError(f"require: cannot read {abs_path}: {e}")

            # Create child environment for the module
            module_env = Environment(parent=env)
            module_env.define('__file__', abs_path)

            # Track loading
            _loading_stack.append(abs_path)
            try:
                exprs = parse(source)
                for expr in exprs:
                    evaluate(expr, module_env)
            finally:
                _loading_stack.pop()

            # Collect exports — whatever was `provide`d or everything if not
            exports = module_env.bindings.get('__exports__', None)
            if exports is None:
                # No provide — export everything defined directly in this module
                exported = {k: v for k, v in module_env.bindings.items()
                           if not k.startswith('__')}
            else:
                exported = {k: module_env.bindings[k]
                           for k in exports
                           if k in module_env.bindings}

            # Cache and import
            _loaded_modules[abs_path] = exported
            for name, val in exported.items():
                env.define(name, val)

            return None

        # (provide name1 name2 ...)
        # Mark specific names for export from this module.
        # If provide is not called, all names are exported.
        if isinstance(head, Symbol) and head.name == 'provide':
            export_names = [r.name if isinstance(r, Symbol) else str(r)
                           for r in rest]
            existing = env.bindings.get('__exports__', [])
            env.define('__exports__', existing + export_names)
            return None
        fn_val = evaluate(head, env)

        if isinstance(fn_val, Macro):
            # Hygiene: macro receives unevaluated AST, expands in its own env
            # but the expansion runs in the *caller's* env
            macro_env = fn_val.env.extend(fn_val.params, rest)
            expanded = None
            for expr in fn_val.body[:-1]:
                evaluate(expr, macro_env)
            expanded = evaluate(fn_val.body[-1], macro_env)
            # Now evaluate the expansion in the caller's env
            return _eval_step(expanded, env)

        # ── Function application ──────────────────────────────
        args = [evaluate(arg, env) for arg in rest]

        if isinstance(fn_val, Builtin):
            return fn_val.fn(*args)

        if isinstance(fn_val, Lambda):
            return TailCall(fn_val, args)

        if callable(fn_val):
            return fn_val(*args)

        raise SchematicError(f"Not a function: {fn_val!r}")

    raise SchematicError(f"Cannot evaluate: {ast!r}")


# ─────────────────────────────────────────────
# STANDARD ENVIRONMENT
# Built-in functions
# ─────────────────────────────────────────────

def make_standard_env() -> Environment:
    env = Environment()

    def builtin(name):
        def decorator(fn):
            env.define(name, Builtin(name, fn))
            return fn
        return decorator

    # Arithmetic
    @builtin('+')
    def add(*args): return sum(args)

    @builtin('-')
    def sub(*args):
        if len(args) == 1: return -args[0]
        return args[0] - sum(args[1:])

    @builtin('*')
    def mul(*args):
        r = 1
        for a in args: r *= a
        return r

    @builtin('/')
    def div(a, b): return a / b

    @builtin('//')
    def idiv(a, b): return a // b

    @builtin('mod')
    def mod(a, b): return a % b

    @builtin('**')
    def power(a, b): return a ** b

    # Comparison
    @builtin('=')
    def eq(*args): return all(args[i] == args[i+1] for i in range(len(args)-1))

    # Structural equality — works on any value including symbols, lists, keywords
    @builtin('equal?')
    def equal_(a, b): return a == b

    @builtin('<')
    def lt(a, b): return a < b

    @builtin('>')
    def gt(a, b): return a > b

    @builtin('<=')
    def lte(a, b): return a <= b

    @builtin('>=')
    def gte(a, b): return a >= b

    @builtin('not')
    def not_(a): return a is False or a is None

    # List operations
    @builtin('cons')
    def cons(h, t): return SList(h, t)

    @builtin('car')
    def car(lst):
        if not isinstance(lst, SList):
            raise SchematicError(f"car: not a list: {lst!r}")
        return lst.head

    @builtin('cdr')
    def cdr(lst):
        if not isinstance(lst, SList):
            raise SchematicError(f"cdr: not a list: {lst!r}")
        return lst.tail

    @builtin('list')
    def make_list(*args): return python_list_to_slist(list(args))

    @builtin('null?')
    def is_null(x): return x is None

    @builtin('pair?')
    def is_pair(x): return isinstance(x, SList)

    @builtin('list?')
    def is_list(x): return isinstance(x, SList) or x is None

    @builtin('length')
    def length(lst): return len(slist_to_python(lst))

    @builtin('append')
    def append(*lists):
        items = []
        for lst in lists:
            items.extend(slist_to_python(lst))
        return python_list_to_slist(items)

    @builtin('reverse')
    def reverse(lst): return python_list_to_slist(list(reversed(slist_to_python(lst))))

    @builtin('map')
    def map_(fn, lst):
        result = []
        node = lst
        while node is not None:
            result.append(_apply(fn, [node.head]))
            node = node.tail
        return python_list_to_slist(result)

    @builtin('filter')
    def filter_(fn, lst):
        result = []
        node = lst
        while node is not None:
            if _apply(fn, [node.head]) is not False and _apply(fn, [node.head]) is not None:
                result.append(node.head)
            node = node.tail
        return python_list_to_slist(result)

    @builtin('fold')
    def fold(fn, init, lst):
        result = init
        node = lst
        while node is not None:
            result = _apply(fn, [result, node.head])
            node = node.tail
        return result

    @builtin('nth')
    def nth(lst, n): return slist_to_python(lst)[n]

    @builtin('first')
    def first(lst): return slist_to_python(lst)[0]

    @builtin('second')
    def second(lst): return slist_to_python(lst)[1]

    @builtin('last')
    def last(lst): return slist_to_python(lst)[-1]

    # Vector operations
    @builtin('vec')
    def vec(*args): return Vector(tuple(args))

    @builtin('vec-get')
    def vec_get(v, i): return v.items[i]

    @builtin('vec-len')
    def vec_len(v): return len(v.items)

    @builtin('vec-conj')
    def vec_conj(v, x): return Vector(v.items + (x,))

    # Map operations
    @builtin('hash-map')
    def hash_map(*args):
        if len(args) % 2 != 0:
            raise SchematicError("hash-map: requires even number of args")
        pairs = tuple(zip(args[::2], args[1::2]))
        return SchematicMap(pairs)

    @builtin('get')
    def get(m, k, default=None):
        return m.to_dict().get(k, default)

    @builtin('assoc')
    def assoc(m, k, v):
        d = m.to_dict()
        d[k] = v
        return SchematicMap(tuple(d.items()))

    @builtin('dissoc')
    def dissoc(m, k):
        d = m.to_dict()
        d.pop(k, None)
        return SchematicMap(tuple(d.items()))

    @builtin('keys')
    def keys(m): return python_list_to_slist(list(m.to_dict().keys()))

    @builtin('vals')
    def vals(m): return python_list_to_slist(list(m.to_dict().values()))

    # Type predicates
    @builtin('number?')
    def is_number(x): return isinstance(x, (int, float)) and not isinstance(x, bool)

    @builtin('string?')
    def is_string(x): return isinstance(x, str)

    @builtin('symbol?')
    def is_symbol(x): return isinstance(x, Symbol)

    @builtin('keyword?')
    def is_keyword(x): return isinstance(x, Keyword)

    @builtin('boolean?')
    def is_boolean(x): return isinstance(x, bool)

    @builtin('procedure?')

    # String operations
    @builtin('str')
    def str_(*args): return ''.join(schematic_str(a) for a in args)

    @builtin('str-len')
    def str_len(s): return len(s)

    @builtin('str-split')
    def str_split(s, sep=None):
        if sep is None or sep == '':
            return python_list_to_slist(list(s))
        return python_list_to_slist(s.split(sep))

    @builtin('str-join')
    def str_join(lst, sep=''):
        return sep.join(slist_to_python(lst))

    @builtin('substring')
    def substring(s, start, end=None): return s[start:end]

    # I/O
    @builtin('print')
    def print_(*args):
        print(' '.join(schematic_str(a) for a in args))
        return None

    @builtin('println')
    def println(*args):
        print(' '.join(schematic_str(a) for a in args))
        return None

    @builtin('display')
    def display(x):
        print(schematic_display(x), end='')
        return None

    # Math
    @builtin('abs')
    def abs_(x): return abs(x)

    @builtin('max')
    def max_(*args): return max(args)

    @builtin('min')
    def min_(*args): return min(args)

    @builtin('floor')
    def floor_(x): return int(x)

    @builtin('sqrt')
    def sqrt_(x): return x ** 0.5

    @builtin('even?')
    def is_even(x): return x % 2 == 0

    @builtin('odd?')
    def is_odd(x): return x % 2 != 0

    @builtin('zero?')
    def is_zero(x): return x == 0

    @builtin('positive?')
    def is_positive(x): return x > 0

    @builtin('negative?')
    def is_negative(x): return x < 0

    # Control
    @builtin('apply')
    def apply_(fn, args):
        return _apply(fn, slist_to_python(args))

    @builtin('eval')
    def eval_(expr):
        return evaluate(expr, env)

    @builtin('error')
    def error(*args):
        raise SchematicError(' '.join(schematic_str(a) for a in args))

    @builtin('assert')
    def assert_(cond, msg='Assertion failed'):
        if cond is False or cond is None:
            raise SchematicError(str(msg))
        return True

    # Symbol/keyword creation
    @builtin('symbol')
    def make_symbol(s): return Symbol(s)

    @builtin('keyword')
    def make_keyword(s): return Keyword(s)

    @builtin('symbol->string')
    def symbol_to_string(s): return s.name

    @builtin('string->symbol')
    def string_to_symbol(s): return Symbol(s)

    # Gensym for hygienic macros
    _gensym_counter = [0]
    @builtin('gensym')
    def gensym(prefix='g'):
        _gensym_counter[0] += 1
        return Symbol(f"{prefix}{_gensym_counter[0]}")

    # ── Python FFI ────────────────────────────────────────────────
    # (python-import "numpy")          → the numpy module
    # (python-import "numpy" :as "np") → bound as np in env
    # (py-call obj "method" arg...)    → obj.method(args...)
    # (py-call fn arg...)              → fn(args...)  when obj is callable
    # (py-attr obj "attr")             → obj.attr
    # (py-set! obj "attr" val)         → obj.attr = val  (mutation, use sparingly)
    # (py-get obj key)                 → obj[key]  (for dicts, lists, etc.)
    # (py->list obj)                   → convert Python iterable to SList
    # (py->vec obj)                    → convert Python iterable to Vector
    # (list->py lst)                   → convert SList to Python list
    # (scm->py val)                    → convert Schematic value to Python
    # (py->scm val)                    → convert Python value to Schematic

    def _scm_to_py(val):
        """Convert Schematic value to Python."""
        if val is None: return None
        if isinstance(val, (bool, int, float, str)): return val
        if isinstance(val, Keyword): return val.name
        if isinstance(val, Symbol): return val.name
        if isinstance(val, SList): return [_scm_to_py(x) for x in slist_to_python(val)]
        if isinstance(val, Vector): return [_scm_to_py(x) for x in val.items]
        if isinstance(val, SchematicMap):
            return {_scm_to_py(k): _scm_to_py(v) for k, v in val.pairs}
        return val  # pass through Python objects as-is

    def _py_to_scm(val):
        """Convert Python value to Schematic."""
        if val is None: return None
        if isinstance(val, bool): return val
        if isinstance(val, (int, float, str)): return val
        if isinstance(val, list):
            return python_list_to_slist([_py_to_scm(x) for x in val])
        if isinstance(val, tuple):
            return Vector(tuple(_py_to_scm(x) for x in val))
        if isinstance(val, dict):
            return SchematicMap(tuple(
                (_py_to_scm(k), _py_to_scm(v)) for k, v in val.items()
            ))
        return val  # pass through arbitrary Python objects

    @builtin('python-import')
    def python_import(module_name, *args):
        """(python-import "numpy") or (python-import "numpy" :as :np)"""
        import importlib
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            raise SchematicError(f"python-import: {e}")
        # Handle :as keyword — bind in env
        if len(args) == 2 and isinstance(args[0], Keyword) and args[0].name == 'as':
            alias = args[1].name if isinstance(args[1], Keyword) else str(args[1])
            env.define(alias, mod)
        return mod

    @builtin('py-call')
    def py_call(obj, *args):
        """
        (py-call obj "method" arg...)  → calls obj.method(args...) — raw Python return
        (py-call callable arg...)      → calls callable(args...)   — raw Python return
        Args are auto-converted from Schematic to Python.
        Return value stays as a Python object — use py->scm or py->list to convert.
        """
        try:
            if args and isinstance(args[0], str):
                # Method call: (py-call obj "method" arg...)
                method_name = args[0]
                method = getattr(obj, method_name)
                py_rest = [_scm_to_py(a) for a in args[1:]]
                return method(*py_rest)
            else:
                # Direct call: (py-call callable arg...)
                py_args = [_scm_to_py(a) for a in args]
                return obj(*py_args)
        except AttributeError as e:
            raise SchematicError(f"py-call: no method: {e}")
        except Exception as e:
            raise SchematicError(f"py-call: {e}")

    @builtin('py-attr')
    def py_attr(obj, attr):
        """(py-attr obj "attr") → obj.attr  — raw Python value, no auto-conversion"""
        try:
            name = attr.name if isinstance(attr, (Symbol, Keyword)) else str(attr)
            return getattr(obj, name)
        except AttributeError as e:
            raise SchematicError(f"py-attr: {e}")

    @builtin('py-set!')
    def py_set(obj, attr, val):
        """(py-set! obj "attr" val) — sets obj.attr = val"""
        try:
            name = attr.name if isinstance(attr, (Symbol, Keyword)) else str(attr)
            setattr(obj, name, _scm_to_py(val))
            return None
        except Exception as e:
            raise SchematicError(f"py-set!: {e}")

    @builtin('py-get')
    def py_get(obj, key):
        """(py-get obj key) → obj[key] — raw Python value"""
        try:
            return obj[_scm_to_py(key)]
        except Exception as e:
            raise SchematicError(f"py-get: {e}")

    @builtin('py-call*')
    def py_call_star(obj, args_list):
        """(py-call* callable schematic-list) — apply callable to a Schematic list of args"""
        try:
            py_args = [_scm_to_py(x) for x in slist_to_python(args_list)]
            return obj(*py_args)
        except Exception as e:
            raise SchematicError(f"py-call*: {e}")

    @builtin('py->list')
    def py_to_list(obj):
        """Convert any Python iterable to a Schematic list."""
        try:
            return python_list_to_slist([_py_to_scm(x) for x in obj])
        except Exception as e:
            raise SchematicError(f"py->list: {e}")

    @builtin('py->vec')
    def py_to_vec(obj):
        """Convert any Python iterable to a Schematic vector."""
        try:
            return Vector(tuple(_py_to_scm(x) for x in obj))
        except Exception as e:
            raise SchematicError(f"py->vec: {e}")

    @builtin('list->py')
    def list_to_py(lst):
        """Convert a Schematic list to a Python list."""
        return [_scm_to_py(x) for x in slist_to_python(lst)]

    @builtin('scm->py')
    def scm_to_py_builtin(val):
        return _scm_to_py(val)

    @builtin('py->scm')
    def py_to_scm_builtin(val):
        return _py_to_scm(val)

    @builtin('py-isinstance?')
    def py_isinstance(obj, type_name):
        """(py-isinstance? obj "int") — check Python type"""
        import builtins
        try:
            t = getattr(builtins, str(type_name), None)
            if t is None:
                return False
            return isinstance(obj, t)
        except Exception:
            return False

    # ── end Python FFI ────────────────────────────────────────────

    # Quasiquote support
    env.define('nil', None)
    env.define('true', True)
    env.define('false', False)
    env.define('#t', True)
    env.define('#f', False)

    return env


def _get_all_names(env: Environment) -> set:
    """Get all names defined in an environment chain."""
    names = set()
    e = env
    while e:
        names.update(e.bindings.keys())
        e = e.parent
    return names


def _apply(fn, args: list) -> Any:
    """Apply a function to a list of already-evaluated arguments."""
    if isinstance(fn, Builtin):
        return fn.fn(*args)
    if isinstance(fn, Lambda):
        result = TailCall(fn, args)
        while isinstance(result, TailCall):
            f = result.fn
            a = result.args
            if isinstance(f, Lambda):
                new_env = f.env.extend(f.params, a)
                for expr in f.body[:-1]:
                    evaluate(expr, new_env)
                result = _eval_step(f.body[-1], new_env)
            elif isinstance(f, Builtin):
                result = f.fn(*a)
            else:
                raise SchematicError(f"Not callable: {f!r}")
        return result
    if callable(fn):
        return fn(*args)
    raise SchematicError(f"Not a function: {fn!r}")


# ─────────────────────────────────────────────
# DISPLAY / PRINTING
# ─────────────────────────────────────────────

def schematic_str(val) -> str:
    """Human-readable representation (like Scheme's display)."""
    if val is None: return '()'
    if val is True: return '#t'
    if val is False: return '#f'
    if isinstance(val, str): return val
    if isinstance(val, float) and val == int(val): return str(int(val))
    return repr(val)

def schematic_display(val) -> str:
    """Full representation (like Scheme's write)."""
    if val is None: return '()'
    if val is True: return '#t'
    if val is False: return '#f'
    if isinstance(val, str): return f'"{val}"'
    if isinstance(val, float) and val == int(val): return str(int(val))
    return repr(val)


# ─────────────────────────────────────────────
# PRELUDE
# Core library written in Schematic itself
# ─────────────────────────────────────────────

PRELUDE = """
(define (identity x) x)

(define (compose f g) (lambda (x) (f (g x))))

(define (flip f) (lambda (x y) (f y x)))

(define (curry f) (lambda (x) (lambda (y) (f x y))))

(define (cadr lst) (car (cdr lst)))
(define (caddr lst) (car (cdr (cdr lst))))
(define (cadddr lst) (car (cdr (cdr (cdr lst)))))

(define (list-tail lst n)
  (if (= n 0) lst (list-tail (cdr lst) (- n 1))))

(define (member? x lst)
  (cond
    ((null? lst) false)
    ((= (car lst) x) true)
    (else (member? x (cdr lst)))))

(define (for-each f lst)
  (if (null? lst)
    nil
    (begin (f (car lst)) (for-each f (cdr lst)))))

(define (range start end)
  (if (>= start end)
    nil
    (cons start (range (+ start 1) end))))

(define (zip lst1 lst2)
  (if (or (null? lst1) (null? lst2))
    nil
    (cons (list (car lst1) (car lst2))
          (zip (cdr lst1) (cdr lst2)))))

(define (flatten lst)
  (cond
    ((null? lst) nil)
    ((pair? (car lst)) (append (flatten (car lst)) (flatten (cdr lst))))
    (else (cons (car lst) (flatten (cdr lst))))))

(define (take n lst)
  (if (or (= n 0) (null? lst))
    nil
    (cons (car lst) (take (- n 1) (cdr lst)))))

(define (drop n lst)
  (if (or (= n 0) (null? lst))
    lst
    (drop (- n 1) (cdr lst))))

(define (any? pred lst)
  (cond
    ((null? lst) false)
    ((pred (car lst)) true)
    (else (any? pred (cdr lst)))))

(define (all? pred lst)
  (cond
    ((null? lst) true)
    ((not (pred (car lst))) false)
    (else (all? pred (cdr lst)))))

(define (sum lst) (fold + 0 lst))
(define (product lst) (fold * 1 lst))

(define-macro (when condition body)
  (list 'if condition body nil))

(define-macro (unless condition body)
  (list 'if condition nil body))
"""


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def make_env(filepath: str = None) -> Environment:
    """Create a fresh environment with standard library."""
    env = make_standard_env()
    # Prelude is written in classic s-expressions — parse without sweet mode
    exprs = parse(PRELUDE, sweet=False)
    for expr in exprs:
        evaluate(expr, env)
    # Set __file__ for require resolution
    if filepath:
        env.define('__file__', os.path.abspath(filepath))
    return env

def run(source: str, env: Environment = None, sweet: bool = True,
        filepath: str = None) -> Any:
    """Parse and evaluate source, return last value."""
    if env is None:
        env = make_env(filepath=filepath)
    exprs = parse(source, sweet=sweet)
    result = None
    for expr in exprs:
        result = evaluate(expr, env)
    return result


# ─────────────────────────────────────────────
# REPL
# ─────────────────────────────────────────────

BANNER = """\
  ╔═══════════════════════════════════════╗
  ║   Schematic  v0.1.0  (Python core)   ║
  ║   A next-gen Lisp                    ║
  ║   Type (exit) or Ctrl-D to quit      ║
  ╚═══════════════════════════════════════╝
"""

def _setup_readline(env: Environment):
    """Configure readline for history, tab completion, and arrow keys."""
    try:
        import readline
        import atexit
        import os

        # History file
        history_file = os.path.expanduser('~/.schematic_history')
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(1000)
        atexit.register(readline.write_history_file, history_file)

        # Detect macOS libedit vs GNU readline
        is_libedit = 'libedit' in readline.__doc__ if readline.__doc__ else False

        def _get_completions(env):
            names = set()
            e = env
            while e:
                names.update(e.bindings.keys())
                e = e.parent
            names.update([
                'define', 'lambda', 'let', 'let*', 'begin', 'if', 'cond',
                'and', 'or', 'match', 'define-macro', 'import', 'quote',
                'quasiquote', 'when', 'unless', 'true', 'false', 'nil',
            ])
            names.update([',load', ',env', ',help'])
            return sorted(names)

        def completer(text, state):
            try:
                word = text.lstrip('(')
                completions = [
                    name for name in _get_completions(env)
                    if name.startswith(word)
                ]
                if state < len(completions):
                    match = completions[state]
                    prefix = text[:len(text) - len(word)]
                    return prefix + match
                return None
            except Exception:
                return None

        readline.set_completer(completer)
        readline.set_completer_delims(' \t\n()[]{}"\';')

        if is_libedit:
            readline.parse_and_bind('bind ^I rl_complete')
        else:
            readline.parse_and_bind('tab: complete')

        if is_libedit:
            try:
                readline.parse_and_bind('bind ^A beginning-of-line')
                readline.parse_and_bind('bind ^E end-of-line')
            except Exception:
                pass
        else:
            readline.parse_and_bind(r'"\e[A": history-search-backward')
            readline.parse_and_bind(r'"\e[B": history-search-forward')
            readline.parse_and_bind(r'"\C-a": beginning-of-line')
            readline.parse_and_bind(r'"\C-e": end-of-line')

        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────
# ANSI COLORS
# ─────────────────────────────────────────────

class C:
    """ANSI color codes."""
    RESET   = '\033[0m'
    BOLD    = '\033[1m'
    # Syntax colors
    KEYWORD = '\033[38;5;141m'   # purple  — define, lambda, if, match
    BUILTIN = '\033[38;5;75m'    # blue    — map, filter, fold, cons
    NUMBER  = '\033[38;5;215m'   # orange  — 42, 3.14
    STRING  = '\033[38;5;150m'   # green   — "hello"
    KEYWORD_VAL = '\033[38;5;203m'  # red  — :ok, :error
    PAREN   = '\033[38;5;240m'   # grey    — ( )
    RESULT  = '\033[38;5;222m'   # yellow  — => result
    ERROR   = '\033[38;5;203m'   # red     — errors
    COMMENT = '\033[38;5;59m'    # dark grey
    PROMPT  = '\033[38;5;141m'   # purple  — λ >
    DEPTH   = '\033[38;5;240m'   # grey    — continuation dots


_SPECIAL_FORMS = {
    'define', 'lambda', 'let', 'let*', 'begin', 'if', 'cond',
    'and', 'or', 'match', 'define-macro', 'import', 'quote',
    'quasiquote', 'when', 'unless', 'set!', 'do',
}

_BUILTIN_NAMES = {
    'map', 'filter', 'fold', 'cons', 'car', 'cdr', 'list', 'append',
    'length', 'reverse', 'null?', 'pair?', 'not', 'equal?', 'apply',
    'eval', 'error', 'assert', 'range', 'zip', 'take', 'drop',
    'flatten', 'any?', 'all?', 'for-each', 'print', 'display',
    'str', 'number?', 'string?', 'symbol?', 'boolean?',
    'py-call', 'py-attr', 'py->list', 'py->scm', 'scm->py',
    'list->py', 'py-get', 'py-set!', 'hash-map', 'get', 'assoc',
    'keys', 'vals', 'vec', 'vec-get', 'vec-len', 'vec-conj',
    '+', '-', '*', '/', '=', '<', '>', '<=', '>=', 'mod', 'abs',
}


def _highlight(source: str) -> str:
    """
    Apply syntax highlighting to a Schematic source string.
    Simple token-by-token colorizer — not a full parser.
    """
    import re
    result = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        # Comments
        if ch == ';':
            end = source.find('\n', i)
            end = end if end != -1 else n
            result.append(C.COMMENT + source[i:end] + C.RESET)
            i = end
            continue

        # Strings
        if ch == '"':
            j = i + 1
            while j < n and source[j] != '"':
                if source[j] == '\\':
                    j += 1
                j += 1
            j += 1
            result.append(C.STRING + source[i:j] + C.RESET)
            i = j
            continue

        # Keywords :foo
        if ch == ':':
            j = i + 1
            while j < n and source[j] not in ' \t\n()[]{},"\'':
                j += 1
            result.append(C.KEYWORD_VAL + source[i:j] + C.RESET)
            i = j
            continue

        # Numbers
        if ch.isdigit() or (ch == '-' and i + 1 < n and source[i+1].isdigit()):
            j = i + 1
            while j < n and (source[j].isdigit() or source[j] == '.'):
                j += 1
            result.append(C.NUMBER + source[i:j] + C.RESET)
            i = j
            continue

        # Parens and brackets
        if ch in '()[]{}':
            result.append(C.PAREN + ch + C.RESET)
            i += 1
            continue

        # Symbols — check if keyword or builtin
        if ch not in ' \t\n,`\'@':
            j = i
            while j < n and source[j] not in ' \t\n()[]{},"\'`:':
                j += 1
            word = source[i:j]
            if word in _SPECIAL_FORMS:
                result.append(C.KEYWORD + C.BOLD + word + C.RESET)
            elif word in _BUILTIN_NAMES:
                result.append(C.BUILTIN + word + C.RESET)
            elif word in ('true', 'false', 'nil', '#t', '#f'):
                result.append(C.NUMBER + word + C.RESET)
            else:
                result.append(word)
            i = j
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


def _highlight_value(val) -> str:
    """Colorize a display value for REPL output."""
    s = schematic_display(val)
    return _highlight(s)


def _paren_report(buf: list) -> str:
    """
    After adding a line, report paren status helpfully.
    If unbalanced, show which line has the unmatched open paren.
    """
    source = '\n'.join(buf)
    depth, balanced, _ = _paren_status(source)
    if balanced:
        return ''
    # Find the unmatched opens
    opens = []
    in_string = False
    for lineno, line in enumerate(buf, 1):
        for col, ch in enumerate(line, 1):
            if ch == '"':
                in_string = not in_string
            if in_string:
                continue
            if ch in '([{':
                opens.append((lineno, col, ch))
            elif ch in ')]}':
                if opens:
                    opens.pop()
    if opens:
        reports = ', '.join(
            f'line {l} col {c}' for l, c, _ in opens[-3:]
        )
        return f'{C.DEPTH}  ({depth} open: {reports}){C.RESET}'
    return ''


def _paren_status(source: str) -> tuple:
    """
    Returns (depth, is_balanced, last_open_pos).
    depth > 0 means we're inside unclosed parens.
    """
    depth = 0
    in_string = False
    last_open = 0
    for i, ch in enumerate(source):
        if ch == '"' and not in_string:
            in_string = True
        elif ch == '"' and in_string:
            in_string = False
        elif not in_string:
            if ch in '([{':
                depth += 1
                last_open = i
            elif ch in ')]}':
                depth -= 1
    return depth, depth <= 0, last_open


def _continuation_prompt(buf: list) -> str:
    """Prompt showing paren depth."""
    if not buf:
        return f'{C.PROMPT}λ{C.RESET} > '
    source = '\n'.join(buf)
    depth, balanced, _ = _paren_status(source)
    if depth <= 0:
        return f'{C.PROMPT}λ{C.RESET} > '
    indent = '  ' * min(depth, 6)
    dots = f'{C.DEPTH}{"·" * min(depth, 3)}{C.RESET}'
    return f'{indent}{dots} '


def _make_prompt_toolkit_session(env):
    """
    Build a prompt_toolkit PromptSession with live syntax highlighting,
    bracket matching, history, and completion.
    Returns the session, or None if prompt_toolkit isn't available.
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.lexers import Lexer
        from prompt_toolkit.styles import Style
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.document import Document
        import os

        # ── Lexer ──────────────────────────────────────────────
        class SchematicLexer(Lexer):
            def lex_document(self, document):
                def get_tokens(line_no):
                    line = document.lines[line_no]
                    tokens = []
                    i = 0
                    n = len(line)
                    while i < n:
                        ch = line[i]
                        # Comment
                        if ch == ';':
                            tokens.append(('class:comment', line[i:]))
                            break
                        # String
                        if ch == '"':
                            j = i + 1
                            while j < n and line[j] != '"':
                                if line[j] == '\\': j += 1
                                j += 1
                            j += 1
                            tokens.append(('class:string', line[i:j]))
                            i = j
                            continue
                        # Keyword :foo
                        if ch == ':':
                            j = i + 1
                            while j < n and line[j] not in ' \t()[]{},"\'':
                                j += 1
                            tokens.append(('class:keyword-val', line[i:j]))
                            i = j
                            continue
                        # Number
                        if ch.isdigit() or (ch == '-' and i+1 < n and line[i+1].isdigit()):
                            j = i + 1
                            while j < n and (line[j].isdigit() or line[j] == '.'):
                                j += 1
                            tokens.append(('class:number', line[i:j]))
                            i = j
                            continue
                        # Parens
                        if ch in '()[]{}':
                            tokens.append(('class:paren', ch))
                            i += 1
                            continue
                        # Symbols
                        if ch not in ' \t,`\'@':
                            j = i
                            while j < n and line[j] not in ' \t()[]{},"\'`:':
                                j += 1
                            word = line[i:j]
                            if word in _SPECIAL_FORMS:
                                tokens.append(('class:special-form', word))
                            elif word in _BUILTIN_NAMES:
                                tokens.append(('class:builtin', word))
                            elif word in ('true', 'false', 'nil', '#t', '#f'):
                                tokens.append(('class:number', word))
                            else:
                                tokens.append(('', word))
                            i = j
                            continue
                        tokens.append(('', ch))
                        i += 1
                    return tokens
                return get_tokens

        # ── Style ──────────────────────────────────────────────
        style = Style.from_dict({
            'special-form': 'bold #af87ff',   # purple bold — define, lambda
            'builtin':      '#5fafd7',         # blue — map, filter
            'number':       '#ffaf5f',         # orange — 42
            'string':       '#afd787',         # green — "hello"
            'keyword-val':  '#ff6b6b',         # red — :ok
            'paren':        '#626262',         # grey — ()
            'comment':      '#4e4e4e',         # dark grey
            'prompt':       '#af87ff bold',    # purple — λ
            'completion-menu.completion': 'bg:#1c1c1c #eeeeee',
            'completion-menu.completion.current': 'bg:#af87ff #000000',
        })

        # ── Completer ──────────────────────────────────────────
        class SchematicCompleter(Completer):
            def get_completions(self, document, complete_event):
                word = document.get_word_before_cursor(
                    pattern=re.compile(r'[^\s()[\]{}"\'`,]+')
                )
                if not word:
                    return
                names = set()
                e = env
                while e:
                    names.update(e.bindings.keys())
                    e = e.parent
                names.update(_SPECIAL_FORMS)
                names.update(_BUILTIN_NAMES)
                names.update(['true', 'false', 'nil'])
                for name in sorted(names):
                    if name.startswith(word):
                        yield Completion(name, start_position=-len(word))

        # ── Session ────────────────────────────────────────────
        history_file = os.path.expanduser('~/.schematic_history')
        session = PromptSession(
            lexer=SchematicLexer(),
            style=style,
            completer=SchematicCompleter(),
            auto_suggest=AutoSuggestFromHistory(),
            history=FileHistory(history_file),
            mouse_support=False,
            complete_while_typing=False,  # Tab only, not auto-popup
        )
        return session

    except ImportError:
        return None


def repl():
    print(BANNER)
    env = make_env()

    # Try prompt_toolkit first, fall back to readline
    pt_session = _make_prompt_toolkit_session(env)

    if pt_session is None:
        _setup_readline(env)
        print("  (prompt_toolkit not found — install it for input highlighting)")
        print("  (pip install prompt_toolkit)")
        print()

    print(f"  Commands: {C.BUILTIN},load <file>  ,env  ,help{C.RESET}  exit  Ctrl-D to quit")
    print()

    buf = []
    last_result = None

    def _get_line(prompt_str):
        """Get a line using prompt_toolkit or fallback input()."""
        if pt_session:
            from prompt_toolkit.formatted_text import HTML
            # Build colored prompt
            if buf:
                depth, _, _ = _paren_status('\n'.join(buf))
                indent = '  ' * min(depth, 6)
                dots = '·' * min(depth, 3)
                pt_prompt = f'{indent}<ansibrightblack>{dots}</ansibrightblack> '
            else:
                pt_prompt = '<bold><ansimagenta>λ</ansimagenta></bold> > '
            from prompt_toolkit.formatted_text import ANSI
            return pt_session.prompt(ANSI(
                _continuation_prompt(buf).encode().decode()
            ))
        else:
            return input(prompt_str)

    while True:
        prompt = _continuation_prompt(buf)

        try:
            if pt_session:
                # prompt_toolkit handles its own prompt formatting
                from prompt_toolkit.formatted_text import ANSI
                # Strip ANSI codes for pt since it handles colors itself
                clean_prompt = prompt.replace(C.PROMPT, '').replace(
                    C.RESET, '').replace(C.DEPTH, '')
                line = pt_session.prompt(clean_prompt)
            else:
                line = input(prompt)
        except EOFError:
            print('\nGoodbye.')
            break
        except KeyboardInterrupt:
            if buf:
                print(f'  {C.DEPTH}(cancelled){C.RESET}')
                buf = []
            else:
                print()
            continue

        stripped = line.strip()

        # Exit commands
        if stripped in ('exit', '(exit)', ',exit', 'quit', ',quit'):
            print('Goodbye.')
            break

        # REPL commands (,command style)
        if stripped.startswith(','):
            parts = stripped[1:].split(None, 1)
            cmd = parts[0] if parts else ''
            arg = parts[1] if len(parts) > 1 else ''

            if cmd == 'load':
                if not arg:
                    print('  Usage: ,load <filename>')
                else:
                    try:
                        with open(arg.strip()) as f:
                            source = f.read()
                        result = run(source, env)
                        print(f'  Loaded {arg.strip()}')
                        if result is not None:
                            print(f'  => {schematic_display(result)}')
                    except FileNotFoundError:
                        print(f'  Error: file not found: {arg.strip()}')
                    except (SchematicError, ParseError, LexError) as e:
                        print(f'  Error: {e}')
            elif cmd == 'env':
                # Show user-defined names (not builtins)
                user_defs = [
                    k for k in env.bindings
                    if not isinstance(env.bindings[k], Builtin)
                ]
                if user_defs:
                    print('  Defined:', ' '.join(sorted(user_defs)))
                else:
                    print('  No user definitions yet.')
            elif cmd == 'help':
                print("""
  Schematic REPL commands:
    ,load <file>   Load and evaluate a .scm file
    ,env           Show user-defined names
    ,help          Show this help
    exit / Ctrl-D  Quit

  Language quick reference:
    (define (f x) body)       define a function
    (lambda (x) body)         anonymous function
    (let ((x 1)) body)        local binding
    (match expr (p => b) ...) pattern match
    (import "mod" :as :name)  import Python module
    (py-call obj "method" ..) call Python method
    `(a ,b ,@c)               quasiquote / unquote

  Arrow keys, Ctrl-A/E, and history search all work.
  Tab completes defined names.
""")
            else:
                print(f'  Unknown command: ,{cmd}  (try ,help)')
            continue

        # Blank line while buffering — show hint
        if not stripped and buf:
            depth, _, _ = _paren_status('\n'.join(buf))
            print(f'  ({depth} unclosed paren{"s" if depth != 1 else ""} — Ctrl-C to cancel)')
            continue

        # Blank line with empty buffer — ignore
        if not stripped and not buf:
            continue

        buf.append(line)
        source = '\n'.join(buf)

        # Show paren status after each line while buffering
        if buf and len(buf) > 1:
            report = _paren_report(buf)
            if report:
                print(report)

        # Check balance — only evaluate when parens are closed
        if _balanced(source):
            if source.strip():
                try:
                    result = run(source, env)
                    last_result = result
                    if result is not None:
                        highlighted = _highlight_value(result)
                        print(f'  {C.RESULT}=>{C.RESET} {highlighted}')
                except (ParseError, SchematicError, LexError) as e:
                    print(f'  {C.ERROR}Error:{C.RESET} {e}')
                except Exception as e:
                    print(f'  {C.ERROR}Internal error:{C.RESET} {e}')
            buf = []


def _balanced(source: str) -> bool:
    """Check if parentheses are balanced enough to try parsing."""
    depth = 0
    in_string = False
    for ch in source:
        if ch == '"' and not in_string:
            in_string = True
        elif ch == '"' and in_string:
            in_string = False
        elif not in_string:
            if ch in '([{': depth += 1
            elif ch in ')]}': depth -= 1
    return depth <= 0


if __name__ == '__main__':
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        try:
            with open(filepath) as f:
                source = f.read()
        except FileNotFoundError:
            print(f"schematic: file not found: {filepath}", file=sys.stderr)
            sys.exit(1)

        # Keep source lines for error reporting
        source_lines = source.splitlines()

        env = make_env(filepath=filepath)
        try:
            run(source, env, filepath=filepath)
        except (SchematicError, ParseError, LexError) as e:
            err = str(e)
            # Enrich with source line if we have a line number in the message
            print(f"\n\033[31mError\033[0m in {filepath}: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n\033[31mInternal error\033[0m: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        repl()