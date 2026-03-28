"""
Test suite for Schematic.
Run with: python test_schematic.py
"""
import sys
sys.path.insert(0, '.')
from schematic import run, make_env, parse, Symbol, Keyword, SList, Vector, SchematicError, python_list_to_slist

passed = 0
failed = 0

def test(description, source, expected):
    global passed, failed
    env = make_env()
    try:
        result = run(source, env)
        if result == expected:
            print(f"  ✓  {description}")
            passed += 1
        else:
            print(f"  ✗  {description}")
            print(f"       expected: {expected!r}")
            print(f"       got:      {result!r}")
            failed += 1
    except Exception as e:
        print(f"  ✗  {description}")
        print(f"       raised: {e}")
        failed += 1

def test_error(description, source):
    global passed, failed
    env = make_env()
    try:
        run(source, env)
        print(f"  ✗  {description} (expected error, got none)")
        failed += 1
    except SchematicError:
        print(f"  ✓  {description}")
        passed += 1
    except Exception as e:
        print(f"  ✓  {description} (raised {type(e).__name__})")
        passed += 1

def section(name):
    print(f"\n── {name} {'─' * (40 - len(name))}")


section("Atoms & self-evaluation")
test("integer",           "42",           42)
test("float",             "3.14",         3.14)
test("string",            '"hello"',      "hello")
test("true",              "true",         True)
test("false",             "false",        False)
test("nil",               "nil",          None)
test("keyword",           ":ok",          Keyword("ok"))
test("keyword equality",  "(= :ok :ok)",  True)


section("Arithmetic")
test("addition",          "(+ 1 2)",        3)
test("subtraction",       "(- 10 3)",       7)
test("multiplication",    "(* 4 5)",        20)
test("division",          "(/ 10 2)",       5.0)
test("nested",            "(+ (* 2 3) 4)",  10)
test("unary minus",       "(- 5)",          -5)
test("modulo",            "(mod 10 3)",     1)
test("power",             "(** 2 8)",       256)


section("Comparison")
test("equal",             "(= 1 1)",     True)
test("not equal",         "(= 1 2)",     False)
test("less than",         "(< 1 2)",     True)
test("greater than",      "(> 2 1)",     True)
test("not",               "(not false)", True)
test("not truthy",        "(not 42)",    False)


section("Variables & define")
test("define and use",
    "(define x 10) x",
    10)
test("define function shorthand",
    "(define (square x) (* x x)) (square 5)",
    25)
test("redefine",
    "(define x 1) (define x 2) x",
    2)


section("Lambda & closures")
test("lambda",
    "((lambda (x) (* x x)) 4)",
    16)
test("closure captures env",
    "(define (make-adder n) (lambda (x) (+ x n))) ((make-adder 5) 3)",
    8)
test("closure counter",
    """
    (define (make-counter)
      (define count 0)
      (lambda ()
        (define count (+ count 1))
        count))
    (define c (make-counter))
    (c)
    """,
    1)


section("Conditionals")
test("if true",           "(if true 1 2)",          1)
test("if false",          "(if false 1 2)",          2)
test("if no else",        "(if false 1)",            None)
test("cond first",        "(cond ((= 1 1) :yes))",   Keyword("yes"))
test("cond else",
    "(cond ((= 1 2) :no) (else :yes))",
    Keyword("yes"))
test("and short circuit",
    "(and true true true)",
    True)
test("and fails",
    "(and true false true)",
    False)
test("or first true",
    "(or false false 42)",
    42)


section("Let bindings")
test("let",
    "(let ((x 1) (y 2)) (+ x y))",
    3)
test("let*",
    "(let* ((x 2) (y (* x 3))) y)",
    6)
test("let scope",
    "(define x 10) (let ((x 99)) x)",
    99)
test("let doesn't leak",
    "(define x 10) (let ((y 5)) y) x",
    10)


section("List operations")
test("cons",              "(cons 1 nil)",             SList(1, None))
test("car",               "(car (list 1 2 3))",       1)
test("cdr",               "(cdr (list 1 2 3))",       SList(2, SList(3, None)))
test("null? empty",       "(null? nil)",              True)
test("null? nonempty",    "(null? (list 1))",         False)
test("length",            "(length (list 1 2 3))",    3)
test("append",
    "(append (list 1 2) (list 3 4))",
    SList(1, SList(2, SList(3, SList(4, None)))))
test("reverse",
    "(reverse (list 1 2 3))",
    SList(3, SList(2, SList(1, None))))
test("list quote",
    "'(1 2 3)",
    SList(1, SList(2, SList(3, None))))


section("Pattern matching")
test("match number",
    "(match 1 (1 => :one) (2 => :two))",
    Keyword("one"))
test("match wildcard",
    "(match 99 (1 => :one) (_ => :other))",
    Keyword("other"))
test("match symbol bind",
    "(match 42 (n => n))",
    42)
test("match list",
    "(match (list 1 2) ((1 2) => :yes) (_ => :no))",
    Keyword("yes"))
test("match list binds",
    "(match (list 1 2) ((a b) => (+ a b)))",
    3)
test("match keyword",
    "(match :ok (:ok => true) (_ => false))",
    True)
test("match in function",
    """
    (define (describe n)
      (match n
        (0 => :zero)
        (1 => :one)
        (_ => :many)))
    (describe 0)
    """,
    Keyword("zero"))


section("Prelude functions")
test("range",
    "(length (range 0 10))",
    10)
test("map",
    "(map (lambda (x) (* x 2)) (list 1 2 3))",
    SList(2, SList(4, SList(6, None))))
test("filter",
    "(filter odd? (list 1 2 3 4 5))",
    SList(1, SList(3, SList(5, None))))
test("fold sum",
    "(fold + 0 (list 1 2 3 4 5))",
    15)
test("any?",
    "(any? even? (list 1 3 4 5))",
    True)
test("all?",
    "(all? odd? (list 1 3 5))",
    True)
test("take",
    "(take 3 (list 1 2 3 4 5))",
    SList(1, SList(2, SList(3, None))))
test("drop",
    "(drop 2 (list 1 2 3 4 5))",
    SList(3, SList(4, SList(5, None))))
test("zip",
    "(zip (list 1 2) (list :a :b))",
    SList(
        SList(1, SList(Keyword("a"), None)),
        SList(SList(2, SList(Keyword("b"), None)), None)
    ))
test("compose",
    "((compose (lambda (x) (* x 2)) (lambda (x) (+ x 1))) 3)",
    8)


section("Macros")
test("when true",
    "(when true :yes)",
    Keyword("yes"))
test("when false",
    "(when false :yes)",
    None)
test("unless false",
    "(unless false :yes)",
    Keyword("yes"))
test("define-macro",
    """
    (define-macro (my-and a b)
      (list 'if a b false))
    (my-and true 42)
    """,
    42)
test("macro short circuit",
    """
    (define-macro (my-and a b)
      (list 'if a b false))
    (my-and false (error "should not eval"))
    """,
    False)
test("macro generates code",
    """
    (define-macro (square-it x)
      (list '* x x))
    (square-it (+ 1 2))
    """,
    9)


section("Tail call optimization")
test("tail recursive sum doesn't stack overflow",
    """
    (define (loop n acc)
      (if (= n 0)
        acc
        (loop (- n 1) (+ acc 1))))
    (loop 100000 0)
    """,
    100000)
test("mutual recursion",
    """
    (define (my-even? n)
      (if (= n 0) true (my-odd? (- n 1))))
    (define (my-odd? n)
      (if (= n 0) false (my-even? (- n 1))))
    (my-even? 100)
    """,
    True)


section("Immutability")
test("list is immutable - cons makes new list",
    """
    (define a (list 1 2 3))
    (define b (cons 0 a))
    (car a)
    """,
    1)
test("vector",
    "(vec-get (vec 1 2 3) 1)",
    2)
test("vec-conj makes new vector",
    """
    (define v (vec 1 2 3))
    (define v2 (vec-conj v 4))
    (vec-len v)
    """,
    3)


section("Quasiquote")
test("plain quasiquote",
    "`(1 2 3)",
    SList(1, SList(2, SList(3, None))))
test("unquote",
    "(define x 99) `(a ,x c)",
    SList(Symbol('a'), SList(99, SList(Symbol('c'), None))))
test("unquote expression",
    "`(result ,(+ 1 2))",
    SList(Symbol('result'), SList(3, None)))
test("unquote-splicing",
    "(define lst '(2 3)) `(1 ,@lst 4)",
    SList(1, SList(2, SList(3, SList(4, None)))))
test("quasiquote in macro",
    """
    (define-macro (double-if cond a b)
      `(if ,cond (* ,a 2) (* ,b 2)))
    (double-if true 3 5)
    """,
    6)
test("nested quasiquote builds code",
    """
    (define op '+)
    (define a 3)
    (define b 4)
    (eval `(,op ,a ,b))
    """,
    7)


section("Pattern matching — rest patterns")
test("rest captures tail",
    "(match '(1 2 3 4) (a b . rest) => rest)",
    SList(3, SList(4, None)))
test("rest empty",
    "(match '(1) (a . rest) => rest)",
    None)
test("rest head",
    "(match '(1 2 3) (a . _) => a)",
    1)
test("rest in function",
    """
    (define (second-onwards lst)
      (match lst
        (_ x . rest) => (cons x rest)))
    (second-onwards '(1 2 3 4))
    """,
    SList(2, SList(3, SList(4, None))))


section("Pattern matching — guards")
test("guard passes",
    "(match 15 (n when (> n 10) => :big) (_ => :small))",
    Keyword("big"))
test("guard fails falls through",
    "(match 5 (n when (> n 10) => :big) (_ => :small))",
    Keyword("small"))
test("guard with binding",
    "(match '(3 3) (a b when (= a b) => :equal) (_ => :diff))",
    Keyword("equal"))
test("guard miss",
    "(match '(3 4) (a b when (= a b) => :equal) (_ => :diff))",
    Keyword("diff"))
test("multiple guards",
    """
    (define (classify n)
      (match n
        (n when (< n 0)   => :negative)
        (n when (= n 0)   => :zero)
        (n when (even? n) => :positive-even)
        (_ => :positive-odd)))
    (list (classify -3) (classify 0) (classify 4) (classify 7))
    """,
    python_list_to_slist([
        Keyword("negative"), Keyword("zero"),
        Keyword("positive-even"), Keyword("positive-odd")
    ]))


section("Pattern matching — or/and/(?)") 
test("or pattern hit",
    "(match 4 (or 2 4 6) => :small-even (_ => :other))",
    Keyword("small-even"))
test("or pattern miss",
    "(match 3 (or 2 4 6) => :small-even (_ => :other))",
    Keyword("other"))
test("and pattern both bind",
    "(match 5 (and n (? odd?)) => n (_ => :no))",
    5)
test("and pattern guard fails",
    "(match 4 (and n (? odd?)) => n (_ => :no))",
    Keyword("no"))
test("? predicate",
    "(match 42 (? even?) => :yes (_ => :no))",
    Keyword("yes"))
test("? predicate fails",
    "(match 43 (? even?) => :yes (_ => :no))",
    Keyword("no"))

test_error("undefined symbol",   "x")
test_error("arity mismatch",     "(define (f x) x) (f 1 2)")
test_error("car of non-list",    "(car 42)")
test_error("no match",           "(match 99 (1 => :one))")


# ─────────────────────────────────────
print(f"\n{'═'*44}")
total = passed + failed
print(f"  {passed}/{total} tests passed", end="")
if failed == 0:
    print("  🎉")
else:
    print(f"  ({failed} failed)")
print(f"{'═'*44}")
sys.exit(0 if failed == 0 else 1)
