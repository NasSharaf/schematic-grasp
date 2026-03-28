;;; grasp-proto.scm — GRASP graph homoiconicity prototype
;;; Combines graph.scm + grasp-rw.scm into one file
;;; since require/provide aren't in Stage 0 yet.
;;;
;;; Run with: python schematic.py grasp-proto.scm

;;; ════════════════════════════════════════════════════
;;; PART 1: graph.scm — Graph data structure
;;; ════════════════════════════════════════════════════

(define (cddr x) (cdr (cdr x)))
(define (cdddr x) (cdr (cdr (cdr x))))
(define (cddddr x) (cdr (cdr (cdr (cdr x)))))

(define (make-graph nodes edges) (list :graph nodes edges))
(define (make-node name expr)    (list :node name expr))
(define (make-edge from to type) (list :edge from to type))

(define (graph? x) (and (pair? x) (equal? (car x) :graph)))
(define (node? x)  (and (pair? x) (equal? (car x) :node)))
(define (edge? x)  (and (pair? x) (equal? (car x) :edge)))

(define (graph-nodes g) (cadr g))
(define (graph-edges g) (caddr g))
(define (node-name n)   (cadr n))
(define (node-expr n)   (caddr n))
(define (edge-from e)   (cadr e))
(define (edge-to e)     (caddr e))
(define (edge-type e)   (cadddr e))

(define (graph-node-names g)
  (map node-name (graph-nodes g)))

(define (graph-find-node g name)
  (let ((matches (filter (lambda (n) (equal? (node-name n) name))
                         (graph-nodes g))))
    (if (null? matches) nil (car matches))))

(define (graph-edges-from g name)
  (filter (lambda (e) (equal? (edge-from e) name))
          (graph-edges g)))

(define (graph-edges-to g name)
  (filter (lambda (e) (equal? (edge-to e) name))
          (graph-edges g)))

(define (graph-successors g name)
  (map edge-to (graph-edges-from g name)))

(define (graph-predecessors g name)
  (map edge-from (graph-edges-to g name)))

(define (graph-roots g)
  (filter (lambda (n)
            (null? (graph-edges-to g (node-name n))))
          (graph-nodes g)))

(define (graph-leaves g)
  (filter (lambda (n)
            (null? (graph-edges-from g (node-name n))))
          (graph-nodes g)))

(define (graph-back-edges g)
  (filter (lambda (e) (equal? (edge-type e) :back))
          (graph-edges g)))

(define (graph-forward-edges g)
  (filter (lambda (e) (not (equal? (edge-type e) :back)))
          (graph-edges g)))

(define (graph-add-node g node)
  (make-graph (cons node (graph-nodes g)) (graph-edges g)))

(define (graph-add-edge g edge)
  (make-graph (graph-nodes g) (cons edge (graph-edges g))))

(define (graph-remove-node g name)
  (make-graph
    (filter (lambda (n) (not (equal? (node-name n) name)))
            (graph-nodes g))
    (filter (lambda (e)
              (and (not (equal? (edge-from e) name))
                   (not (equal? (edge-to   e) name))))
            (graph-edges g))))

(define (graph-remove-nodes g names)
  (fold (lambda (acc name) (graph-remove-node acc name))
        g
        names))

(define (graph-display g)
  (println "  nodes:")
  (for-each (lambda (n)
              (println (str "    (" (node-name n) " = " (node-expr n) ")")))
            (graph-nodes g))
  (println "  edges:")
  (for-each (lambda (e)
              (println (str "    " (edge-from e)
                            " --[" (edge-type e) "]--> "
                            (edge-to e))))
            (graph-edges g)))

;;; ════════════════════════════════════════════════════
;;; PART 2: grasp-rw.scm — Reader and Writer
;;; ════════════════════════════════════════════════════

(define (grasp-edge-op? sym)
  (or (equal? sym '?seq)
      (equal? sym '?if)
      (equal? sym '?par)
      (equal? sym '?net)
      (equal? sym '?back)))

(define (grasp-op->type op)
  (cond ((equal? op '?seq)  :seq)
        ((equal? op '?if)   :if)
        ((equal? op '?par)  :par)
        ((equal? op '?net)  :net)
        ((equal? op '?back) :back)
        (else :seq)))

(define (type->grasp-op type)
  (cond ((equal? type :seq)  '?seq)
        ((equal? type :if)   '?if)
        ((equal? type :par)  '?par)
        ((equal? type :net)  '?net)
        ((equal? type :back) '?back)
        (else '?seq)))

;;; Reader — surface syntax list → graph

(define (grasp-read stmts)
  (fold grasp-read-stmt (make-graph '() '()) stmts))

(define (grasp-read-stmt g stmt)
  (let ((items (if (pair? stmt) stmt '())))
    (cond
      ;; (?op from to...) — explicit edge statement
      ((and (>= (length items) 3)
            (grasp-edge-op? (car items)))
       (fold (lambda (acc target)
               (graph-add-edge acc
                 (make-edge (cadr items) target
                            (grasp-op->type (car items)))))
             g
             (cddr items)))

      ;; (name = expr ?op target...) — inline node + edges
      ((and (>= (length items) 5)
            (equal? (cadr items) '=)
            (grasp-edge-op? (cadddr items)))
       (let* ((name    (car items))
              (expr    (caddr items))
              (op      (cadddr items))
              (targets (cddddr items))
              (g1      (graph-add-node g (make-node name expr))))
         (fold (lambda (acc target)
                 (graph-add-edge acc
                   (make-edge name target (grasp-op->type op))))
               g1
               targets)))

      ;; (name = expr) — simple node
      ((and (= (length items) 3)
            (equal? (cadr items) '=))
       (graph-add-node g (make-node (car items) (caddr items))))

      (else
       (println (str "  [skip] " stmt))
       g))))

;;; Writer — graph → surface syntax list

(define (grasp-write g)
  (append
    (map (lambda (n) (list (node-name n) '= (node-expr n)))
         (graph-nodes g))
    (map (lambda (e)
           (list (type->grasp-op (edge-type e))
                 (edge-from e)
                 (edge-to e)))
         (graph-edges g))))

;;; Pretty printer

(define (grasp-print stmts)
  (for-each
    (lambda (stmt)
      (let ((items (if (pair? stmt) stmt '())))
        (cond
          ((and (>= (length items) 3)
                (grasp-edge-op? (car items)))
           (for-each (lambda (target)
                       (println (str "    "
                                     (car items) " "
                                     (cadr items)
                                     " -> " target)))
                     (cddr items)))
          ((and (>= (length items) 3)
                (equal? (cadr items) '=))
           (println (str "(" (car items) " = " (caddr items) ")")))
          (else
           (println (str stmt))))))
    stmts))

;;; ════════════════════════════════════════════════════
;;; PART 3: Tests — does the round-trip work?
;;; ════════════════════════════════════════════════════

(println "")
(println "══════════════════════════════════════════")
(println " GRASP Proto — Steps 1 & 2 Verification")
(println "══════════════════════════════════════════")

;;; Test 1: Simple conditional graph

(define conditional-program
  '((input  = x)
    (?seq input check)
    (check  = (> x 0))
    (?if check high low)
    (high   = (* x 2))
    (?seq high output)
    (low    = (+ x 1))
    (?seq low output)
    (output = result)))

(println "")
(println "── Test 1: Conditional graph ──")
(println "Surface syntax:")
(grasp-print conditional-program)
(define g1 (grasp-read conditional-program))
(println "Graph:")
(graph-display g1)
(println (str "roots:  " (map node-name (graph-roots g1))))
(println (str "leaves: " (map node-name (graph-leaves g1))))
(println (str "successors of check: " (graph-successors g1 'check)))

;;; Test 2: Parallel graph

(define parallel-program
  '((request = incoming)
    (request = incoming ?par handler-a handler-b)
    (handler-a = (process-a request))
    (handler-b = (process-b request))
    (?seq handler-a merge)
    (?seq handler-b merge)
    (merge = (combine a b))))

(println "")
(println "── Test 2: Parallel graph ──")
(define g2 (grasp-read parallel-program))
(graph-display g2)
(println (str "roots:  " (map node-name (graph-roots g2))))
(println (str "leaves: " (map node-name (graph-leaves g2))))

;;; Test 3: Graph with back-edge (loop)

(define loop-program
  '((i     = 0)
    (body  = (do-something i))
    (i-inc = (+ i 1))
    (?seq i body)
    (?seq body i-inc)
    (?back i-inc i)
    (exit = done)))

(println "")
(println "── Test 3: Loop graph (with ¿ back-edge) ──")
(define g3 (grasp-read loop-program))
(graph-display g3)
(println (str "back-edges: " (length (graph-back-edges g3))))
(println (str "forward-edges: " (length (graph-forward-edges g3))))

;;; Test 4: Round-trip fidelity

(println "")
(println "── Test 4: Round-trip fidelity ──")
(define rt (grasp-write g1))
(define g1-rt (grasp-read rt))
(println (str "node count preserved: "
              (= (length (graph-nodes g1))
                 (length (graph-nodes g1-rt)))))
(println (str "edge count preserved: "
              (= (length (graph-edges g1))
                 (length (graph-edges g1-rt)))))
(println "Round-trip surface syntax:")
(grasp-print rt)

(println "")
(println "══ Steps 1 & 2 complete. Ready for Step 3. ══")
