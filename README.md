# Grasp

A graph-oriented programming language built on a Lisp foundation. Where Lisp achieves homoiconicity by treating code and data as *lists*, Grasp generalizes this to *graphs* — programs are first-class graphs where nodes compute and edges represent control and data flow.

This repo contains two interrelated projects:

- **Schematic** — A modern Lisp interpreter (Stage 0, complete) written in Python. It is the bootstrap compiler, runtime, and implementation language for Grasp.
- **Grasp** — A graph-oriented language (design complete, implementation in progress) that runs on top of Schematic.

---

## Status

| Component | Status |
|-----------|--------|
| Schematic (Stage 0, Python) | Complete — 136/136 tests passing |
| `mce.scm` — Meta-circular evaluator | Complete — proves self-hosting capability |
| Stage 1 — Schematic-in-Schematic | In progress |
| Stage 2 — WASM backend | Planned |
| Grasp implementation | Planned |

---

## Quick Start

**Requirements:** Python 3.11+

```bash
cd Schematic

# Start the interactive REPL
python3 schematic.py

# Run a file
python3 schematic.py program.scm

# Run the test suite
python3 test_schematic.py
```

Optional: `pip install prompt_toolkit` for syntax highlighting in the REPL.

---

## Schematic

Schematic is a complete Lisp interpreter with a focus on correctness, expressiveness, and self-hosting potential.

### Language Features

| Feature | Description |
|---------|-------------|
| Core forms | `define`, `lambda`, `let`, `let*`, `begin`, `if`, `cond`, `and`, `or` |
| Pattern matching | Wildcards, literals, destructuring, rest patterns, guards, `or`/`and` patterns, vectors |
| Hygienic macros | `define-macro` with automatic gensym renaming to prevent variable capture |
| Sweet expressions | Neoteric `f(x, y)` calls + indentation-based grouping at top level |
| Module system | `require`/`provide` with relative paths and circular dependency detection |
| Content addressing | Every `define`d function is stored by SHA hash of its AST; names are mutable aliases |
| Python FFI | `import`, `py-call`, `py-attr`, `py-set!`, `py-get`, `py->list`, `scm->py` |
| Tail-call optimization | Trampoline-based TCO; tested to 100k+ recursion depth |
| Error messages | Line/column numbers in stack traces |
| REPL | Readline support, tab completion, history, optional syntax highlighting |

### Example

```scheme
; Define a recursive function
(define (factorial n)
  (if (= n 0) 1 (* n (factorial (- n 1)))))

(factorial 10) ; => 3628800

; Closures
(define (make-adder n)
  (lambda (x) (+ x n)))

((make-adder 5) 3) ; => 8

; Pattern matching
(match (list 1 2 3)
  ((a b c) => (+ a b c))
  (_ => 0)) ; => 6

; Hygienic macros
(define-macro (swap! a b)
  (let ((tmp a))
    (set! a b)
    (set! b tmp)))

; Python FFI
(define math (import "math"))
(py-call math "sqrt" 144) ; => 12.0
```

### REPL Commands

| Command | Description |
|---------|-------------|
| `,load <file>` | Load and evaluate a `.scm` file |
| `,env` | Show user-defined names |
| `,help` | Show help text |
| `exit` or Ctrl-D | Quit |

### Built-in Functions

**Arithmetic:** `+` `-` `*` `/` `//` `mod` `**`

**Comparison:** `=` `equal?` `<` `>` `<=` `>=` `not`

**Lists:** `cons` `car` `cdr` `list` `null?` `pair?` `length` `append` `reverse` `map` `filter` `fold` `nth` `first` `last`

**Vectors:** `vec` `vec-get` `vec-len` `vec-conj`

**Hash maps:** `hash-map` `get` `assoc` `dissoc` `keys` `vals`

**Strings:** `str` `str-len` `str-split` `str-join` `substring`

**Type predicates:** `number?` `string?` `symbol?` `keyword?` `boolean?` `procedure?`

**Meta:** `apply` `eval` `error` `assert` `gensym` `symbol->string` `string->symbol`

**Content addressing:** `hash-of` `same-definition?` `definition-at` `diff`

---

## Content Addressing

Every function defined in Schematic is identified by a SHA hash of its normalized AST. Names are mutable pointers to hashes — the underlying definition is immutable.

```scheme
(define (double x) (* 2 x))
(hash-of double)         ; => "a3f7..."

(define (double x) (* x 2))  ; semantically identical
(same-definition? double double) ; => #t — same hash despite textual difference
```

This enables auditable refactoring, content-based caching, and a path toward Binary Lambda Calculus normalization for multiple compilation backends.

---

## Meta-Circular Evaluator

`mce.scm` is a complete Schematic interpreter written in Schematic — a proof that the language is powerful enough to express its own semantics.

```scheme
(require "mce.scm")
(define env (mce-base-env))

(mce-eval '(+ 1 2) env)                               ; => 3
(mce-eval '((lambda (x) (* x x)) 5) env)              ; => 25

(define env (mce-eval
  '(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))
  env))
(mce-eval '(fact 10) env)                             ; => 3628800
```

---

## Grasp Language

Grasp is a graph-oriented language where programs are first-class graphs. Nodes contain Schematic expressions; edges represent control and data flow.

### Node Syntax

```scheme
(name = expr)  ; a node named `name` that evaluates `expr`
```

### Edge Operators

| Operator | Meaning |
|----------|---------|
| `?seq` | Sequential — single successor |
| `?if` | Conditional branch — value selects path |
| `?par` | Parallel fork — all successors active simultaneously |
| `?net` | Network propagation — weighted edges, matrix multiplication |
| `¿name` | Back-edge (cycle) — carries value from the *previous* clock tick |

### Execution Model

Grasp programs execute as synchronous reactive systems (in the tradition of Lustre/Esterel/SCADE):

- Each clock tick, all nodes evaluate in topological order
- Back-edges (`¿`) carry values from the previous tick (SSA semantics)
- Programs map naturally to Petri nets, enabling deadlock detection and liveness proofs

### Formal Verification

Grasp programs compile mechanically to TLA+ specifications. The synchronous reactive model provides:

- Deadlock freedom guarantees
- Liveness and boundedness checking
- Counterexamples rendered in Grasp syntax

---

## Architecture

### Evaluation Pipeline

```
Source Text
    ↓  tokenize()  — regex-based lexer, indentation-aware at top level
Token Stream
    ↓  parse()     — sweet-expression-aware parser
AST (SList / Symbol / Vector / SchematicMap)
    ↓  evaluate()  — trampoline evaluator with TCO
Values
```

### Self-Hosting Stages

| Stage | Implementation | Status |
|-------|----------------|--------|
| 0 | Python (`schematic.py`) | Complete |
| 1 | Schematic (`schematic.scm`) | In progress |
| 2 | WebAssembly | Planned |

Stage 1 consists of: `stdlib.scm`, `test.scm`, `store.scm`, `match.scm`, `hygiene.scm`, `modules.scm`, `repl.scm`, and a final `schematic.scm` that combines them.

### Planned Compilation Targets

Once Stage 2 is complete, Schematic ASTs normalize to Binary Lambda Calculus (BLC), enabling multiple backends from a single frontend:

- **WebAssembly** — Browser and portable deployment
- **LLVM IR** — Native x86 / ARM / RISC-V
- **XLA HLO** — GPU / TPU acceleration
- **TLA+** — Formal verification
- **RISC-V VM** — Blockchain / embedded systems

---

## Project Structure

```
Schematic/
├── schematic.py          # Stage 0 interpreter (~2,550 lines)
├── test_schematic.py     # Test suite (136 tests)
├── mce.scm               # Meta-circular evaluator
├── SPEC.md               # Complete language specification
└── grasp/
    ├── graph.scm         # Graph data structures and traversal
    ├── grasp-proto.scm   # Grasp prototype
    ├── grasp-eval.scm    # Grasp evaluator (synchronous reactive semantics)
    └── experiments.scm   # Graph algorithm experiments
```

---

## Running the Tests

```bash
cd Schematic
python3 test_schematic.py
```

Tests cover: atoms and self-evaluation, arithmetic, comparisons, variables, closures, conditionals, let bindings, lists, pattern matching, prelude functions, macros, content addressing, Python FFI, modules, error handling, and special forms.

---

## Specification

See [SPEC.md](Schematic/SPEC.md) for the complete language specification covering Schematic syntax, semantics, the self-hosting roadmap, and the full Grasp language design.
