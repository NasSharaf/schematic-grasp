;;; ─────────────────────────────────────────────────────────────────
;;; SCHEMATIC META-CIRCULAR EVALUATOR
;;; A Schematic interpreter written in Schematic.
;;;
;;; This is the self-describing heart of the language — proof that
;;; Schematic is powerful enough to define its own semantics.
;;;
;;; Usage:
;;;   (require "mce.scm")
;;;   (mce-eval '(+ 1 2) (mce-base-env))     ; => 3
;;;   (mce-eval '(define (f x) (* x x)) env)
;;;   (mce-eval '(f 5) env)                   ; => 25
;;;
;;; Content addressing: every function defined here is stored by hash.
;;; Try: (hash-of mce-eval)
;;; ─────────────────────────────────────────────────────────────────

(provide
  mce-eval
  mce-apply
  mce-base-env
  mce-env-lookup
  mce-env-define
  mce-env-extend
  mce-make-env
  mce-tagged?
  mce-error)


;;; ── Environments ──────────────────────────────────────────────────
;;; An environment is a list of frames.
;;; Each frame is a list of (name . value) pairs.
;;; The empty environment is nil.

(define (mce-make-env) (list (list)))

(define (mce-env-lookup name env)
  (let ((name-str (if (symbol? name) (symbol->string name) name)))
    (if (null? env)
      (error (str "MCE: unbound variable: " name-str))
      (let ((frame (car env)))
        (let ((binding (mce-frame-lookup name-str frame)))
          (if binding
            (let ((val (cdr binding)))
              (if (mce-box? val) (mce-unbox val) val))
            (mce-env-lookup name-str (cdr env))))))))

(define (mce-frame-lookup name frame)
  (cond
    ((null? frame) false)
    ((equal? (car (car frame)) name) (car frame))
    (else (mce-frame-lookup name (cdr frame)))))

(define (mce-env-define name val env)
  (let ((frame (car env)))
    (cons (cons (cons name val) frame) (cdr env))))

(define (mce-env-extend params args env)
  (cons (mce-make-frame params args) env))

(define (mce-make-frame params args)
  (if (null? params)
    (list)
    (let ((name (if (symbol? (car params))
                  (symbol->string (car params))
                  (car params))))
      (cons (cons name (car args))
            (mce-make-frame (cdr params) (cdr args))))))


;;; ── Tagged values ─────────────────────────────────────────────────
;;; We represent MCE closures, primitives, and boxes as tagged lists:
;;;   (:closure params body env)
;;;   (:primitive fn)
;;;   (:box value)   — a mutable reference cell for recursive defines

(define (mce-tagged? tag x)
  (and (pair? x) (equal? (car x) tag)))

(define (mce-closure?   x) (mce-tagged? :closure x))
(define (mce-primitive? x) (mce-tagged? :primitive x))
(define (mce-box?       x) (mce-tagged? :box x))

(define (mce-make-closure params body env)
  (list :closure params body env))

(define (mce-closure-params c) (cadr c))
(define (mce-closure-body  c) (caddr c))
(define (mce-closure-env   c) (cadddr c))

(define (mce-make-primitive fn) (list :primitive fn))
(define (mce-primitive-fn p)    (cadr p))

;;; Mutable box — used for recursive defines so closures can
;;; reference themselves before they're fully constructed.
;;; Uses Schematic's make-box/unbox/box-set! builtins.

(define (mce-box val)     (list :box (make-box val)))
(define (mce-unbox box)   (unbox (cadr box)))
(define (mce-box-set! box val) (box-set! (cadr box) val))


;;; ── Error helper ──────────────────────────────────────────────────

(define (mce-error msg . args)
  (error (fold str msg args)))


;;; ── Core evaluator ────────────────────────────────────────────────

(define (mce-eval expr env)
  (match expr

    ;; Self-evaluating: numbers, strings, booleans, nil, keywords
    ((? number?)  => expr)
    ((? string?)  => expr)
    (true         => true)
    (false        => false)
    (nil          => nil)
    ((? keyword?) => expr)

    ;; Symbol — look up in environment
    ((? symbol?) =>
     (mce-env-lookup (symbol->string expr) env))

    ;; (quote x) — return unevaluated
    (('quote datum) => datum)

    ;; (if condition then else?)
    (('if condition then) =>
     (if (mce-eval condition env)
       (mce-eval then env)
       nil))

    (('if condition then else) =>
     (if (mce-eval condition env)
       (mce-eval then env)
       (mce-eval else env)))

    ;; (define name val) — simple value define
    (('define (? symbol?) val) =>
     (let ((v (mce-eval val env)))
       (mce-env-define (symbol->string (cadr expr)) v env)))

    ;; (define (name params...) body...) — function define with recursion support
    ;; Uses a mutable box so the closure can reference itself.
    ;; Standard SICP trick: bind name to a box, create closure over that env,
    ;; then fill the box. Lookup unwraps boxes transparently.
    (('define (? pair?) . body) =>
     (let* ((name-and-params (cadr expr))
            (name-sym  (car name-and-params))
            (name-str  (symbol->string name-sym))
            (params    (map symbol->string (mce-list->native (cdr name-and-params))))
            ;; Step 1: bind name to a fresh empty box
            (box       (mce-box false))
            (new-env   (mce-env-define name-str box env))
            ;; Step 2: make closure over new-env (which contains the box)
            (closure   (mce-make-closure params body new-env)))
       ;; Step 3: fill the box — closure can now find itself via the box
       (mce-box-set! box closure)
       new-env))

    ;; (lambda (params...) body...)
    (('lambda params . body) =>
     (let ((param-names (map symbol->string (mce-list->native params))))
       (mce-make-closure param-names body env)))

    ;; (begin expr...)
    (('begin . exprs) =>
     (mce-eval-sequence exprs env))

    ;; (let ((x v) ...) body...)
    (('let bindings . body) =>
     (let* ((binding-list (mce-list->native bindings))
            (names  (map (lambda (b) (symbol->string (car b)))
                         binding-list))
            (vals   (map (lambda (b) (mce-eval (cadr b) env))
                         binding-list))
            (new-env (mce-env-extend names vals env)))
       (mce-eval-sequence body new-env)))

    ;; (and ...) short-circuit
    (('and) => true)
    (('and x) => (mce-eval x env))
    (('and x . rest) =>
     (let ((v (mce-eval x env)))
       (if v (mce-eval (cons 'and rest) env) false)))

    ;; (or ...) short-circuit
    (('or) => false)
    (('or x) => (mce-eval x env))
    (('or x . rest) =>
     (let ((v (mce-eval x env)))
       (if v v (mce-eval (cons 'or rest) env))))

    ;; (cond (test expr) ... (else expr))
    (('cond . clauses) =>
     (mce-eval-cond clauses env))

    ;; Function application — must be last
    ((? pair?) =>
     (let* ((fn      (mce-eval (car expr) env))
            (call-args (map (lambda (a) (mce-eval a env))
                            (mce-list->native (cdr expr)))))
       (mce-apply fn call-args)))

    (_ => (mce-error "MCE: cannot evaluate: " expr))))


;;; ── Apply ─────────────────────────────────────────────────────────

(define (mce-apply fn call-args)
  (cond
    ;; Primitive — call through to Schematic
    ((mce-primitive? fn)
     (apply (mce-primitive-fn fn) call-args))

    ;; Closure — extend env and eval body
    ((mce-closure? fn)
     (let ((new-env (mce-env-extend
                      (mce-list->native (mce-closure-params fn))
                      call-args
                      (mce-closure-env fn))))
       (mce-eval-sequence (mce-list->native (mce-closure-body fn))
                          new-env)))

    (else
     (mce-error "MCE: not a procedure: " fn))))


;;; ── Helpers ───────────────────────────────────────────────────────

(define (mce-eval-sequence exprs env)
  (if (null? (cdr exprs))
    (mce-eval (car exprs) env)
    (begin
      (mce-eval (car exprs) env)
      (mce-eval-sequence (cdr exprs) env))))

(define (mce-eval-cond clauses env)
  (if (null? clauses)
    nil
    (let ((clause (car clauses)))
      (let ((test (car clause))
            (body (cadr clause)))
        (if (or (equal? test 'else)
                (mce-eval test env))
          (mce-eval body env)
          (mce-eval-cond (cdr clauses) env))))))

;;; ── Type predicates for MCE dispatch ─────────────────────────────
;;; These wrap Schematic's builtins with the names mce-eval uses
;;; in its match patterns.

(define (mce-symbol?  x) (symbol? x))
(define (mce-keyword? x) (keyword? x))
(define (mce-number?  x) (number? x))
(define (mce-string?  x) (string? x))
(define (mce-pair?    x) (pair? x))

(define (mce-list->native lst)
  ;; In Schematic, quoted lists ARE native lists — no conversion needed.
  lst)

(define (symbol->string sym)
  ;; Symbol name as a string.
  ;; Schematic's str on a symbol gives its name.
  (str sym))


;;; ── Base environment ──────────────────────────────────────────────
;;; The set of primitives the MCE starts with.
;;; These are Schematic builtins wrapped as MCE primitives.

(define (mce-base-env)
  (fold
    (lambda (env pair)
      (mce-env-define (car pair) (cdr pair) env))
    (mce-make-env)
    (list
      ;; Arithmetic
      (cons "+"    (mce-make-primitive +))
      (cons "-"    (mce-make-primitive -))
      (cons "*"    (mce-make-primitive *))
      (cons "/"    (mce-make-primitive /))
      (cons "mod"  (mce-make-primitive mod))
      (cons "abs"  (mce-make-primitive abs))
      ;; Comparison
      (cons "="      (mce-make-primitive =))
      (cons "<"      (mce-make-primitive <))
      (cons ">"      (mce-make-primitive >))
      (cons "<="     (mce-make-primitive <=))
      (cons ">="     (mce-make-primitive >=))
      (cons "equal?" (mce-make-primitive equal?))
      ;; Logic
      (cons "not"  (mce-make-primitive not))
      ;; Lists
      (cons "cons"    (mce-make-primitive cons))
      (cons "car"     (mce-make-primitive car))
      (cons "cdr"     (mce-make-primitive cdr))
      (cons "list"    (mce-make-primitive list))
      (cons "null?"   (mce-make-primitive null?))
      (cons "pair?"   (mce-make-primitive pair?))
      (cons "length"  (mce-make-primitive length))
      (cons "append"  (mce-make-primitive append))
      (cons "map"     (mce-make-primitive map))
      (cons "filter"  (mce-make-primitive filter))
      (cons "fold"    (mce-make-primitive fold))
      (cons "reverse" (mce-make-primitive reverse))
      ;; Type checks
      (cons "number?"    (mce-make-primitive number?))
      (cons "string?"    (mce-make-primitive string?))
      (cons "procedure?" (mce-make-primitive procedure?))
      (cons "boolean?"   (mce-make-primitive boolean?))
      ;; I/O and misc
      (cons "display" (mce-make-primitive display))
      (cons "str"     (mce-make-primitive str))
      (cons "error"   (mce-make-primitive error))
      (cons "apply"   (mce-make-primitive apply))
      ;; Boolean and nil constants (not wrapped as primitives — they're values)
      (cons "true"  true)
      (cons "false" false)
      (cons "nil"   nil))))
