;;; graph.scm — GRASP graph data structure
;;; A proper module — require this from other files.

(provide
  make-graph make-node make-edge
  graph? node? edge?
  graph-nodes graph-edges
  node-name node-expr
  edge-from edge-to edge-type
  graph-edges-from graph-edges-to
  graph-successors graph-predecessors
  graph-roots graph-leaves
  graph-add-node graph-add-edge
  graph-remove-node graph-remove-nodes
  graph-node-names graph-has-node?
  graph-find-node
  graph-back-edges graph-forward-edges
  graph-display
  set-member? set-add set-union
  set-intersect set-diff set-equal?
  bfs-forward bfs-backward
  grasp-edge-op? grasp-op->type type->grasp-op
  grasp-read grasp-write grasp-print)

(define (cddr x)   (cdr (cdr x)))
(define (cdddr x)  (cdr (cdr (cdr x))))
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

(define (graph-edges-from g name)
  (filter (lambda (e) (equal? (edge-from e) name)) (graph-edges g)))

(define (graph-edges-to g name)
  (filter (lambda (e) (equal? (edge-to e) name)) (graph-edges g)))

(define (graph-successors g name)
  (map edge-to (graph-edges-from g name)))

(define (graph-predecessors g name)
  (map edge-from (graph-edges-to g name)))

(define (graph-roots g)
  (filter (lambda (n) (null? (graph-edges-to g (node-name n))))
          (graph-nodes g)))

(define (graph-leaves g)
  (filter (lambda (n) (null? (graph-edges-from g (node-name n))))
          (graph-nodes g)))

(define (graph-node-names g) (map node-name (graph-nodes g)))

(define (graph-has-node? g name)
  (any? (lambda (n) (equal? (node-name n) name)) (graph-nodes g)))

(define (graph-find-node g name)
  (let ((matches (filter (lambda (n) (equal? (node-name n) name))
                         (graph-nodes g))))
    (if (null? matches) nil (car matches))))

(define (graph-back-edges g)
  (filter (lambda (e) (equal? (edge-type e) :back)) (graph-edges g)))

(define (graph-forward-edges g)
  (filter (lambda (e) (not (equal? (edge-type e) :back))) (graph-edges g)))

(define (graph-add-node g node)
  (make-graph (cons node (graph-nodes g)) (graph-edges g)))

(define (graph-add-edge g edge)
  (make-graph (graph-nodes g) (cons edge (graph-edges g))))

(define (graph-remove-node g name)
  (make-graph
    (filter (lambda (n) (not (equal? (node-name n) name))) (graph-nodes g))
    (filter (lambda (e)
              (and (not (equal? (edge-from e) name))
                   (not (equal? (edge-to   e) name))))
            (graph-edges g))))

(define (graph-remove-nodes g names)
  (fold (lambda (acc name) (graph-remove-node acc name)) g names))

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

(define (set-member? x s) (any? (lambda (e) (equal? e x)) s))

(define (set-add x s) (if (set-member? x s) s (cons x s)))

(define (set-union s1 s2) (fold (lambda (acc x) (set-add x acc)) s1 s2))

(define (set-intersect s1 s2) (filter (lambda (x) (set-member? x s2)) s1))

(define (set-diff s1 s2) (filter (lambda (x) (not (set-member? x s2))) s1))

(define (set-equal? s1 s2)
  (and (= (length s1) (length s2))
       (all? (lambda (x) (set-member? x s2)) s1)))

(define (bfs-forward g start-names)
  (define (step frontier visited)
    (if (null? frontier) visited
        (let* ((node (car frontier))
               (new-vis (set-add node visited))
               (neighbors (map edge-to
                               (filter (lambda (e) (not (equal? (edge-type e) :back)))
                                       (graph-edges-from g node))))
               (unvisited (filter (lambda (n) (not (set-member? n new-vis))) neighbors)))
          (step (append (cdr frontier) unvisited) new-vis))))
  (step start-names '()))

(define (bfs-backward g end-names)
  (define (step frontier visited)
    (if (null? frontier) visited
        (let* ((node (car frontier))
               (new-vis (set-add node visited))
               (neighbors (map edge-from
                               (filter (lambda (e) (not (equal? (edge-type e) :back)))
                                       (graph-edges-to g node))))
               (unvisited (filter (lambda (n) (not (set-member? n new-vis))) neighbors)))
          (step (append (cdr frontier) unvisited) new-vis))))
  (step end-names '()))

(define (grasp-edge-op? sym)
  (or (equal? sym '?seq) (equal? sym '?if)
      (equal? sym '?par) (equal? sym '?net) (equal? sym '?back)))

(define (grasp-op->type op)
  (cond ((equal? op '?seq) :seq) ((equal? op '?if) :if)
        ((equal? op '?par) :par) ((equal? op '?net) :net)
        ((equal? op '?back) :back) (else :seq)))

(define (type->grasp-op type)
  (cond ((equal? type :seq) '?seq) ((equal? type :if) '?if)
        ((equal? type :par) '?par) ((equal? type :net) '?net)
        ((equal? type :back) '?back) (else '?seq)))

(define (grasp-read stmts)
  (fold (lambda (g stmt)
          (let ((items (if (pair? stmt) stmt '())))
            (cond
              ((and (>= (length items) 3) (grasp-edge-op? (car items)))
               (fold (lambda (acc target)
                       (make-graph (graph-nodes acc)
                         (cons (make-edge (cadr items) target
                                          (grasp-op->type (car items)))
                               (graph-edges acc))))
                     g (cddr items)))
              ((and (= (length items) 3) (equal? (cadr items) '=))
               (make-graph (cons (make-node (car items) (caddr items))
                                 (graph-nodes g))
                           (graph-edges g)))
              (else g))))
        (make-graph '() '()) stmts))

(define (grasp-write g)
  (append
    (map (lambda (n) (list (node-name n) '= (node-expr n))) (graph-nodes g))
    (map (lambda (e) (list (type->grasp-op (edge-type e)) (edge-from e) (edge-to e)))
         (graph-edges g))))

(define (grasp-print stmts)
  (for-each (lambda (stmt)
    (let ((items (if (pair? stmt) stmt '())))
      (cond
        ((and (>= (length items) 3) (grasp-edge-op? (car items)))
         (for-each (lambda (t)
                     (println (str "    " (car items) " " (cadr items) " -> " t)))
                   (cddr items)))
        ((and (= (length items) 3) (equal? (cadr items) '=))
         (println (str "(" (car items) " = " (caddr items) ")")))
        (else (println (str stmt))))))
    stmts))
