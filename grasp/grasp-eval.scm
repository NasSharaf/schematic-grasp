;;; grasp-eval.scm — GRASP graph evaluator with ¿ execution semantics
;;;
;;; Implements the execution model for GRASP programs:
;;;   ?seq  — sequential, topological order handles it
;;;   ?if   — conditional branch, routes on truthy/falsy value
;;;   ?par  — parallel fork, all branches active
;;;   ?back — ¿ back-edge, graph-level tail call via trampoline
;;;
;;; Key semantic: when ?back fires, the source node's value
;;; is rebound to the target node's name in grasp-env.
;;; This is what makes loops meaningful.
;;;
;;; Key design: node expressions reference other nodes only
;;; via symbols — substitution replaces them before eval.
;;; Function-position symbols (car of list) are NOT substituted
;;; so Schematic builtins like < + * map etc. still work.

(require "graph.scm")

(provide
  grasp-eval-graph
  grasp-eval-graph-v2
  grasp-run
  grasp-run-v2
  grasp-eval
  grasp-eval-v2
  make-grasp-env
  grasp-env-get
  grasp-env-set
  grasp-env-has?
  topological-order
  eval-node
  node-is-active?
  cycle-back?
  cycle-back-target
  cycle-back-rebind-val
  cycle-back-rebind-name
  cycle-back-env
  validate-back-edges
  loop-body)

;;; ── GRASP environment ────────────────────────────────────────

(define (make-grasp-env) '())

(define (grasp-env-get env name)
  (let ((b (filter (lambda (b) (equal? (car b) name)) env)))
    (if (null? b) nil (cadr (car b)))))

(define (grasp-env-set env name val)
  (cons (list name val)
        (filter (lambda (b) (not (equal? (car b) name))) env)))

(define (grasp-env-has? env name)
  (any? (lambda (b) (equal? (car b) name)) env))

;;; ── Cycle-back marker ────────────────────────────────────────
;;; Returned by route-edges when ¿ fires.
;;; The trampoline catches this and re-enters execution.
;;; rebind-name: the node name to update with source value
;;; rebind-val:  the value to rebind it to
;;; env:         the current grasp-env at time of firing

(define (make-cycle-back target rebind-name rebind-val env)
  (list :cycle-back target rebind-name rebind-val env))
(define (cycle-back? x)
  (and (pair? x) (equal? (car x) :cycle-back)))
(define (cycle-back-target x)       (cadr x))
(define (cycle-back-rebind-name x)  (caddr x))
(define (cycle-back-rebind-val x)   (cadddr x))
(define (cddddr x) (cdr (cdr (cdr (cdr x)))))
(define (cycle-back-env x)          (car (cddddr x)))

;;; ── Expression substitution ──────────────────────────────────
;;; Replace symbols bound in grasp-env with their values.
;;; Function-position symbols (head of list) are left alone
;;; so builtins like < + * map filter etc. remain callable.

(define (grasp-eval-expr expr grasp-env)
  (cond
    ;; Bare symbol — look up directly, don't eval
    ((symbol? expr)
     (let ((name (str expr)))
       (if (grasp-env-has? grasp-env name)
         (grasp-env-get grasp-env name)
         ;; Unknown symbol — return as-is (could be a Schematic global)
         (eval expr))))
    ;; Self-evaluating
    ((not (pair? expr)) expr)
    ;; List expression — substitute args then eval
    (else
     (eval (grasp-subst expr grasp-env)))))

(define (grasp-subst expr grasp-env)
  (cond
    ;; Symbol in arg position — substitute if bound
    ((symbol? expr)
     (let ((name (str expr)))
       (if (grasp-env-has? grasp-env name)
         (list 'quote (grasp-env-get grasp-env name))
         expr)))
    ;; Self-evaluating atoms
    ((not (pair? expr)) expr)
    ;; Quoted — don't touch
    ((equal? (car expr) 'quote) expr)
    ;; List — preserve function position, substitute args
    (else
     (let ((subst-args
            (map (lambda (e) (grasp-subst e grasp-env)) (cdr expr))))
        (cons (car expr) subst-args)))))

;;; ── Topological ordering ─────────────────────────────────────
;;; Returns node names in dependency order.
;;; Ignores :back edges — those are intentional cycles.

(define (topological-order g)
  (define (visit name visited result)
    (if (set-member? name visited)
      (list visited result)
      (let* ((new-vis (set-add name visited))
             (preds   (map edge-from
                           (filter
                             (lambda (e) (not (equal? (edge-type e) :back)))
                             (graph-edges-to g name))))
             (state   (fold (lambda (acc p)
                              (visit p (car acc) (cadr acc)))
                            (list new-vis result) preds)))
        (list (car state)
              (append (cadr state) (list name))))))
  (cadr (fold (lambda (acc n)
                (visit n (car acc) (cadr acc)))
              (list '() '())
              (graph-node-names g))))

;;; ── Edge routing ─────────────────────────────────────────────

(define (route-edges g node-name val edges grasp-env)
  (cond
    ((null? edges) grasp-env)

    ;; ¿ back-edge — graph-level tail call
    ;; When val is truthy: fire the back-edge
    ;; The source node's value rebinds the target node's name
    ;; so the loop variable gets updated each iteration
    ((any? (λ (e) (equal? (edge-type e) :back)) edges)
     (let ((back (car (filter (lambda (e) (equal? (edge-type e) :back))
                              edges)))
           (fwd  (filter (lambda (e) (not (equal? (edge-type e) :back)))
                         edges)))
       (if (and val (not (equal? val false)))
         ;; ¿ fires: rebind target with current source value
         (make-cycle-back (edge-to back)
                          (str (edge-to back))
                          val
                          grasp-env)
         ;; Loop condition false — exit, continue forward
         (if (null? fwd) grasp-env
             (route-edges g node-name val fwd grasp-env)))))

    ;; ?if — take first edge if truthy, second if falsy
    ;; Edges are stored in reverse (cons prepends), so
    ;; last-declared = car. We reverse to match declaration order.
    ((all? (λ (e) (equal? (edge-type e) :if)) edges)
     (let* ((ordered (reverse edges))
            (branch  (if (and val (not (equal? val false)))
                       (edge-to (car ordered))
                       (if (>= (length ordered) 2)
                         (edge-to (cadr ordered))
                         nil))))
       (if branch
         (grasp-env-set grasp-env (str node-name "-branch") branch)
         grasp-env)))

    ;; ?par — mark all targets as parallel-active
    ((all? (λ (e) (equal? (edge-type e) :par)) edges)
     (fold (λ (env e)
             (grasp-env-set env
                            (str node-name "->" (edge-to e))
                            (edge-to e)))
           grasp-env edges))

    ;; ?seq — topological order handles sequencing
    (else grasp-env)))

;;; ── Node evaluator ───────────────────────────────────────────

(define (eval-node g node-name grasp-env)
  ;; If ¿ rebound this node this iteration, skip re-evaluating
  ;; its expression — use the rebound value instead.
  ;; Without this, (counter = 0) would reset to 0 every iteration.
  (let* ((rebound-key (str node-name ":rebound"))
         (was-rebound (grasp-env-has? grasp-env rebound-key))
         (node  (graph-find-node g node-name))
         (expr  (if node (node-expr node) nil))
         (val   (if was-rebound
                  (grasp-env-get grasp-env (str node-name))
                  (if node (grasp-eval-expr expr grasp-env) nil)))
         (env1  (if was-rebound
                  (filter (lambda (b) (not (equal? (car b) rebound-key)))
                          grasp-env)
                  grasp-env))
         (env2  (grasp-env-set env1 (str node-name) val))
         (edges (graph-edges-from g node-name)))
    (route-edges g node-name val edges env2)))

;;; ── Fold with early-exit for cycle-back ─────────────────────
;;; Standard fold would pass cycle-back markers as accumulators.
;;; This version short-circuits the moment one appears.

(define (eval-fold g names grasp-env)
  (if (null? names)
    grasp-env
    (let ((result (eval-node g (car names) grasp-env)))
      (if (cycle-back? result)
        result                          ; short-circuit to trampoline
        (eval-fold g (cdr names) result)))))

;;; ── Main evaluator with ¿ trampoline ─────────────────────────

(define (grasp-eval-graph g initial-env)
  (validate-back-edges g)
  (define (find-from order target)
    (define (find-from-helper lst)
      (cond ((null? lst) '())
            ((equal? (car lst) target) lst)
            (else (find-from-helper (cdr lst)))))
    (find-from-helper order))

  (define (trampoline result)
    (if (cycle-back? result)
      (let* ((target      (cycle-back-target result))
             (rebind-name (cycle-back-rebind-name result))
             (rebind-val  (cycle-back-rebind-val result))
             (env         (cycle-back-env result))
             ;; Update the target's binding with the new value
             ;; This is what makes the loop variable advance
             (new-env     (grasp-env-set
                            (grasp-env-set env rebind-name rebind-val)
                            (str rebind-name ":rebound") true))
             (order       (topological-order g))
             (from        (find-from order target)))
        (trampoline (eval-fold g from new-env)))
      result))

  (trampoline (eval-fold g (topological-order g) initial-env)))

;;; ── Public interface ─────────────────────────────────────────

(define (grasp-run stmts)
  (grasp-eval-graph (grasp-read stmts) (make-grasp-env)))

(define (grasp-eval stmts bindings)
  (let ((init (fold (lambda (env b)
                      (grasp-env-set env (str (car b)) (cadr b)))
                    (make-grasp-env) bindings)))
    (grasp-eval-graph (grasp-read stmts) init)))

;;; ════════════════════════════════════════════════════════════

(println "")
(println "══ grasp-eval loaded ══")

;;; ── Active-set aware evaluator ───────────────────────────────
;;; The basic eval-fold evaluates ALL nodes in topo order.
;;; This works for ?seq and ?par but not ?if — both branches
;;; would evaluate, ignoring the condition.
;;;
;;; eval-fold-active tracks which nodes are reachable
;;; given ?if decisions, only evaluating reachable nodes.

(define (compute-active-set g)
  ;; Start from roots, follow edges respecting ?if decisions
  ;; Returns a function: env -> set of active node names
  ;; (We compute lazily as we evaluate)
  'all-active) ; placeholder — use full eval for now

;;; ── Conditional-aware evaluator ──────────────────────────────
;;; When a ?if node is evaluated, we record the branch taken.
;;; Subsequent nodes in the topo walk check if they're on
;;; an active branch before evaluating.

(define (node-is-active? g node-name grasp-env if-decisions)
  ;; A node is active if all its ?if predecessors chose it
  (let ((if-preds
         (filter (lambda (e) (equal? (edge-type e) :if))
                 (graph-edges-to g node-name))))
    (if (null? if-preds)
      true  ; No ?if predecessors — always active
      ;; Check that at least one ?if pred chose this node
      (any? (λ (e)
              (let ((decision-key (str (edge-from e) "-branch")))
                (equal? (grasp-env-get grasp-env decision-key)
                        node-name)))
            if-preds))))

(define (eval-fold-cond g names grasp-env)
  ;; Like eval-fold but skips nodes not on active ?if branch
  (if (null? names)
    grasp-env
    (let ((node-name (car names))
          (rest      (cdr names)))
      (if (node-is-active? g node-name grasp-env '())
        (let ((result (eval-node g node-name grasp-env)))
          (if (cycle-back? result)
            result
            (eval-fold-cond g rest result)))
        ;; Skip inactive node
        (eval-fold-cond g rest grasp-env)))))

;;; ── Updated grasp-eval-graph using conditional eval ─────────

(define (grasp-eval-graph-v2 g initial-env)
  (validate-back-edges g)
  (define (find-from order target)
    (cond ((null? order) '())
          ((equal? (car order) target) order)
          (else (find-from (cdr order) target))))

  (define (trampoline result)
    (if (cycle-back? result)
      (let* ((target  (cycle-back-target result))
             (new-val (cycle-back-rebind-val result))
             (env     (cycle-back-env result))
             (env2    (grasp-env-set
                       (grasp-env-set env (str target) new-val)
                       (str target ":rebound") true))
             ;; Clear ?if decisions so branch is re-evaluated
             (env3    (filter (lambda (b)
                                (not (let ((k (car b)))
                                       (and (> (length k) 7)
                                            (equal? (substring k
                                                               (- (length k) 7)
                                                               (length k))
                                                    "-branch")))))
                              env2))
             (order   (topological-order g))
             (from    (find-from order target)))
        (trampoline (eval-fold-cond g from env3)))
      result))

  (trampoline (eval-fold-cond g (topological-order g) initial-env)))

(define (grasp-run-v2 stmts)
  (grasp-eval-graph-v2 (grasp-read stmts) (make-grasp-env)))

(define (grasp-eval-v2 stmts bindings)
  (let ((init (fold (λ (env b)
                      (grasp-env-set env (str (car b)) (cadr b)))
                    (make-grasp-env) bindings)))
    (grasp-eval-graph-v2 (grasp-read stmts) init)))

;;; ── Back-edge validator ──────────────────────────────────────
;;; Enforces the constraint that ¿ must close an existing
;;; forward path. For each ?back edge source → target:
;;;   - target must have a forward path to source
;;;   - i.e. source is reachable from target via forward edges
;;;
;;; This is the difference between ¿ and goto.
;;; goto can jump anywhere. ¿ can only close a cycle
;;; that already exists as a forward path in the graph.
;;; The loop body is exactly the nodes on that path.

(define (validate-back-edges g)
  (for-each
    (lambda (back-edge)
      (let* ((source   (edge-from back-edge))
             (target   (edge-to   back-edge))
             (reachable-from-target (bfs-forward g (list target))))
        (if (not (set-member? source reachable-from-target))
          (error (str "Invalid ¿: " source
                      " is not reachable from " target
                      " via forward edges. "
                      "¿ must close an existing forward path, not jump to an unconnected node.")))))
    (graph-back-edges g)))

(define (loop-body g back-edge)
  ;; Returns the set of nodes that form the loop body —
  ;; all nodes on forward paths from target to source.
  ;; These are the nodes that re-evaluate each iteration.
  (let* ((source    (edge-from back-edge))
         (target    (edge-to   back-edge))
         (from-target (bfs-forward  g (list target)))
         (to-source   (bfs-backward g (list source))))
    (set-intersect from-target to-source)))

