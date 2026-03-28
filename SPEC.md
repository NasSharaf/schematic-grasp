# Schematic + GRASP — Project Spec & Status
*A next-generation Lisp and graph-oriented programming language*

---

## The Core Insight

**Lisp's insight:** code and data are lists, so a program can manipulate programs.

**This project's insight:** code and data are graphs, so a program can manipulate programs-as-graphs — and content addressing makes those manipulations safe.

Lisp chose lists as its universal structure not because lists are maximally general, but because they were simple enough to implement in 1958 and homoiconicity gave enormous power at minimal complexity cost. A list is a degenerate graph — a path graph where each node has exactly one successor. Graphs are strictly more general: lists, trees, stacks, and arrays are all special cases of graphs.

If homoiconicity with lists gives you Lisp's power, homoiconicity with graphs should give you more. Programs ARE graphs — the control flow of a concurrent system, the dependency graph of a distributed computation, the message-passing topology of a microservice architecture. These are all graphs that programmers currently draw on whiteboards and encode awkwardly in callbacks, futures, and channels. Making that topology explicit in syntax — first-class, inspectable, transformable — is the graph equivalent of what Lisp did with lists.

Content addressing is not a separate idea bolted on. It exists because graph transformations — through macros, through GRASP's `?par`/`¿` rewriting, through compilation — need to be auditable. The main argument against macros is that they can transform code into something dangerous and irrecoverably different from what you wrote. Content addressing solves this: every transformation has a hash of what went in and a hash of what came out. You can diff them, revert them, inspect them. The same applies to GRASP graph transformations — every rewrite is traceable.

This connects the formal verification story: TLA+ verification of a GRASP program is only meaningful if you can prove that the program you verified is the program that runs. Content addressing gives that guarantee — the hash you verified is the hash that executes. Formal verification without content addressing is verifying a *description* of a program, not the program itself. Most formal methods work ignores this distinction.

The unified statement: **programs have graph structure; GRASP makes that structure first-class; content addressing makes graph transformations safe; formal verification of the graph becomes verification of the running program. Structure, transformation, and verification are expressed in the same formalism.**

### The DSL Universality Claim

Because every other data structure is a special case of a graph, every other computational paradigm is a special case of GRASP.

A list is a path graph. Define the right edge type and you have Lisp — `?seq` edges enforce sequential evaluation, a single successor per node, and homoiconicity gives you s-expressions. Lisp is a DSL in GRASP.

A stack is a list with restricted access. Define push/pop as edge types and you have Forth-style concatenative programming. Forth is a DSL in GRASP.

An array is a path graph with indexed access. A matrix is a 2D grid graph. Define `?net` edges with dense weight matrices and you have APL-style array programming. APL is a DSL in GRASP.

A state machine is a graph where nodes are states and edges are transitions. A decision tree is a directed acyclic graph with branching. A dataflow graph is exactly what `?par` describes.

The claim is not that these DSLs are easy to implement in any language — they are. The claim is that in GRASP, the DSL's *data structure* and the DSL's *execution model* are both expressible as graphs, so the DSL is homoiconic with the host language. A Lisp DSL in GRASP isn't a library that interprets lists — it IS a graph that happens to have list topology, and GRASP can manipulate, verify, and content-address it natively.

This is the deepest version of the graph homoiconicity claim: not just that GRASP can express more than Lisp, but that Lisp, Forth, APL, and any data-structure-specific paradigm are all *derivable* from GRASP by restricting the graph topology. GRASP is the common substrate. The question of which language paradigm is "best" dissolves — they're all views of the same underlying structure.

## The Central Research Question

**Can homoiconicity work with graphs?**

Lisp's homoiconicity works because lists are simple enough that a list-manipulating program naturally looks like a valid Lisp program — code and data share the same structure. For GRASP to have the same property, graph-manipulating programs need to naturally look like GRASP programs.

Graphs are more complex than lists. They have cycles, multiple edge types, topology that matters. The MCE demonstrates the list case still works at the Schematic level — a Schematic interpreter in Schematic is ~300 lines and reads naturally. The GRASP case is unproven. Can you write a GRASP graph transformer that is itself a GRASP program? Does the topology-as-syntax approach remain readable when the program being written is about graph topology?

This is the question the implementation needs to answer. Every design decision in GRASP — the `?`/`¿` syntax, the indentation model, the edge type system — is a bet on "yes." The Petri net simulator (`petri.scm`) is the first test: a graph program written in Schematic. The GRASP self-interpreter will be the definitive test.

---

## The Big Picture

Two connected projects:

**Schematic** — a modern Lisp targeting WebAssembly. The foundation layer. Handles expressions, computation, macros, types, content addressing. Not the end goal — infrastructure for GRASP.

**GRASP** (Graph + Lisp) — a graph-oriented programming language where topology is syntax. Built on top of Schematic. Nodes compute in Schematic; edges and graph structure are GRASP syntax. The longer-term goal.

**The key insight:** Schematic is to GRASP what lambda calculus is to Lisp — the formal substrate the higher-level language is built on. Neither is an end in itself. They are infrastructure for a graph-native computational model that maps cleanly to tensors, Petri nets, and distributed systems.

---

## Architecture: The Self-Hosting Stack

Schematic is designed to express as much of itself as possible. The architecture separates what *must* be written in Python from what *can* be written in Schematic — and the goal is to push that boundary as far down as possible.

### Stage 0 — The Python Scaffold (~800 lines, permanent)

These cannot be written in Schematic. They are the irreducible bootstrap:

```
tokenize()     — reads characters, emits tokens (string ops below language level)
parse()        — tokens → SLists (parser needs the parser to exist)
evaluate()     — trampoline loop + TCO (can't implement TCO from inside a non-TCO language)
input()        — reads from terminal (OS syscall)
py-call/attr   — FFI bridge (needs to understand Python objects)
```

This is the scaffold. It doesn't need to be beautiful — it needs to be correct. Target: ~800 lines of Python. Everything else moves to `.scm`.

### Stage 1 — Schematic in Schematic (.scm files)

Everything that *can* be written in Schematic, *should be*. Each file is a module with `provide`:

```
stdlib.scm      — map, filter, fold, range, zip, flatten, group-by, frequencies...
test.scm        — test runner macro, assert-equal, sections, pass/fail reporting
store.scm       — content addressing logic (hash-of, history-of, diff, store queries)
match.scm       — pattern matching implemented as a macro (the hard one)
hygiene.scm     — macro expansion with hygienic renaming
modules.scm     — require/provide logic, circular detection, relative paths
repl.scm        — REPL loop, commands, display, paren tracking
schematic.scm   — requires all of the above: the complete Schematic interpreter
```

The MCE (`mce.scm`) already demonstrates this is possible. It implements the evaluation *core* in ~300 lines of Schematic. The eight files above extend that core to a complete self-describing language.

### Stage 2 — WASM Backend (self-hosting)

Once Stage 1 is complete, you can run:

```bash
python stage0.py schematic.scm program.scm
```

`stage0.py` evaluates `schematic.scm`, which defines a complete Schematic interpreter, which evaluates `program.scm`. Two layers of interpretation — Stage 0 running Stage 1 running your program. The Python scaffold becomes optional. The language runs anywhere WASM runs.

### Why This Architecture

**It proves the design is coherent.** A language that can't express its own semantics has a gap somewhere. If Schematic can implement pattern matching as a macro library, the macro system is powerful enough. If it can implement hygienic expansion in Schematic code, the meta-programming facilities are adequate.

**It separates essential from accidental.** The Python tokenizer and trampoline are accidental — they exist because you had to start somewhere. The `.scm` modules are essential — the language defining itself. Once they exist, the Python scaffold is disposable.

**The five things test different language properties:**

| Feature | What it tests |
|---|---|
| Pattern matching | Macros powerful enough to extend syntax |
| Hygienic macros | Meta-programming without variable capture |
| Module system | Code organization at scale |
| Content addressing | First-class functions + hashing primitives |
| REPL logic | I/O + stateful programming |

If all five work in Schematic, nothing is missing from the language.

---

## Current Implementation Status

**Stage 0 (Python interpreter):** ~2,500 lines, 136/136 tests passing
**Stage 1 (Schematic stdlib):** `mce.scm` complete (~300 lines), rest in progress
**Stage 2 (WASM):** Not started

**Run:** `python schematic.py` (REPL) or `python schematic.py file.scm`

### What Stage 0 Provides

**Core evaluator** — `define`, `lambda`, `let`, `let*`, `begin`, `if`, `cond`, `and`, `or`, `match`, `define-macro`, `import`, `require`, `provide`

**Pattern matching** — wildcards `_`, literals, quoted symbol literals `'foo`, list destructuring, rest patterns `(a b . rest)`, guards `when`, `or`/`and`/`?` patterns, vector patterns `[p1 p2]`

**Hygienic macros** — `define-macro` with quasiquote. Full hygiene via automatic gensym renaming — introduced symbols renamed to fresh names, no variable capture, no definition leakage

**Sweet expressions** — neoteric `f(x,y)` calls + indentation grouping

**Module system** — `(require "file.scm")` / `(provide f g h)`. Relative paths, export-all default, circular require detection, `__file__` tracking

**Content addressing** — every `define`'d value stored by SHA hash of its AST. Special forms: `hash-of`, `history-of`, `same-definition?`, `current-hash`. Builtins: `definition-at`, `diff`, `store-keys`, `store-names`

**Python FFI** — `import`, `py-call`, `py-attr`, `py-get`, `py-set!`, `py->list`, `py->vec`, `py->scm`, `scm->py`, `list->py`, `py-call*`

**Mutable boxes** — `make-box`, `unbox`, `box-set!`. Used for recursive defines in the MCE; available generally

**Rest params** — `(define (f x . rest) rest)` and `(lambda (x . rest) rest)`

**TCO** — trampoline loop, 100k+ depth. `map`, `filter`, `fold`, `for-each` all go through trampoline

**Error messages** — line numbers, column info, source context

**REPL** — readline/libedit with history, tab completion, syntax highlighting, paren depth tracking, `,load`, `,env`, `,help`

### Known Rough Edges

- No `set!` for mutation (intentional — use boxes where needed)
- Partial `lambda` special-casing in parser (works but is a wart)
- The standard library prelude is still in Python (will move to `stdlib.scm`)

---

## mce.scm — The Meta-Circular Evaluator

The proof of concept for self-hosting. A Schematic interpreter written in Schematic, in ~300 lines.

```scheme
(require "mce.scm")
(define env (mce-base-env))

; Basic evaluation
(mce-eval '(+ 1 2) env)                     ; => 3
(mce-eval '((lambda (x) (* x x)) 5) env)    ; => 25

; Recursive functions via mutable boxes
(define env (mce-eval
  '(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))
  env))
(mce-eval '(fact 10) env)                   ; => 3628800

; Closures
(define env (mce-eval
  '(define (make-adder n) (lambda (x) (+ x n)))
  env))
(mce-eval '((make-adder 10) 5) env)         ; => 15
```

**What the MCE covers:** self-evaluating forms, symbols, `quote`, `if`, `define` (value and function forms with recursion), `lambda`, `begin`, `let`, `and`, `or`, `cond`, function application, higher-order functions, closures, mutual recursion.

**Recursive defines** use mutable boxes (`make-box`, `box-set!`) — the standard SICP trick. A closure references itself through a box that gets filled after construction. Lookups unwrap boxes transparently.

**What's missing from the MCE:** pattern matching, macros, modules, content addressing, FFI. Those are the Stage 1 work items.

### The 300 vs 2500 Line Comparison

The MCE's brevity isn't magic — it stands on Stage 0's shoulders. The Python file provides parsing, TCO, FFI, content addressing, and 50+ builtins. The MCE uses all of those.

What the MCE proves is that the *evaluator kernel* — the essential semantics — is ~300 lines. Everything else is infrastructure. This is SICP's central insight: the metacircular evaluator is always small. The language defines itself; the rest is scaffolding.

---

## Content Addressing

### What It Is

Every `define`'d function is identified by the SHA hash of its normalized AST. Names are mutable aliases pointing to hashes — like git tags pointing to commits.

```scheme
(define (square x) (* x x))
(hash-of square)                  ; => "941e639277ae"

; Same implementation = same hash regardless of name
(define (sq x) (* x x))
(same-definition? square sq)      ; => true

; Redefine creates a new hash, old version preserved
(define (square x) (+ x x))
(hash-of square :all)             ; => ("941e639277ae" "20d4eda9...")

; Retrieve any past version
(definition-at "941e639277ae")    ; => the original square function

; Structural diff between versions
(diff "941e639277ae" "20d4eda9...")
; => (changed (body-changed ((* x x)) ((+ x x))))
```

### Why This Matters

**Rename for free** — renaming `square` to `sq` doesn't change the hash. Callers referencing the hash still work.

**No silent breaking changes** — redefining with different logic produces a new hash. The divergence is explicit.

**No dependency hell** — depend on `#941e639277ae`, not `"square@1.0"`. The hash IS the version. Supply chain attacks impossible.

**Structural diffs** — `body-changed: (* x x) → (+ x x)` rather than "line 1 changed." Better than git for code.

**Automatic deduplication** — two functions with the same implementation get the same hash everywhere.

### The Human Readability Fix

Hashes are identity. Names are *views* over hashes. You still write `square` in code — the name is a mutable pointer to the current hash. Show names by default; show hashes when provenance matters. Both coexist. This is Unison's model, applied more rigorously via BLC normalization.

### The Wizard Problem

Classic Lisp failure mode: a brilliant programmer builds a powerful internal DSL. They leave. Nobody understands it. Company rewrites in Java.

Content addressing solves this structurally:
- `(history-of name)` reconstructs what a definition was at any point
- `(diff h1 h2)` shows structural changes between versions
- `(same-definition? f g)` detects equivalent implementations across names
- Structural search over the AST store finds all callers of any definition

### Merkle-Enhanced ASTs

The current flat content addressing (hash the whole normalized AST) gives semantic identity. Adding Merkle structure to the AST gives incremental verification, structural sharing, and the full git-for-code experience — but at expression granularity rather than file granularity.

**The original insight:** git solved versioning for files by treating them as content-addressed Merkle trees. Schematic applies the same model to code at a finer granularity — not file-level, but definition-level and subexpression-level. Git can tell you "this file changed." Merkle-enhanced Schematic can tell you "this specific subexpression changed, and here are all definitions that transitively depend on it."

**How it works:** Instead of hashing the whole AST as a flat blob, each AST node is hashed as `hash(node_type, hash(child_1), hash(child_2), ...)`. Every subexpression gets its own hash. The definition's hash is the Merkle root over its entire expression tree.

```scheme
; Merkle structure of (define (square x) (* x x))
;
;   root: hash("define", hash("square"), hash(lambda-node))
;              lambda-node: hash("lambda", hash("x"), hash(body))
;                               body: hash("*", hash("x"), hash("x"))
;                                         ^--- leaf hashes are just hash("x"), hash("*")
```

Changing `(* x x)` to `(+ x x)` changes the body hash, the lambda hash, and the root — but nothing else. The leaf hash for `x` is unchanged and shared between both versions.

**What this adds over flat hashing:**

*Incremental verification* — only recheck definitions where the Merkle root changed. This is how Bazel and Nix achieve reproducible incremental builds. Schematic gets it for free once the hash structure is Merkle-shaped.

*Structural sharing* — two definitions that share a subexpression share that subexpression's hash and its storage. A large codebase where many functions call `(map f xs)` stores that pattern once. The deduplication the spec already claims becomes physically real at the storage level, not just semantically true.

*Cheap structural diffs* — `diff` becomes tree-walking: find where the Merkle trees diverge. This is O(changed nodes) not O(total nodes). The current diff compares top-level hashes and returns opaque change descriptions; Merkle diff walks both trees simultaneously and stops at matching hashes, giving you exactly the changed subtrees.

*Distributed code sharing* — a content-addressed package registry where dependencies are Merkle roots rather than flat hashes gets git-style sync: only pull the missing subtrees. Two programs that share a library share the library's Merkle subtree — provably, not just by convention.

*Verified deployment* — a Merkle tree over a deployed contract's AST lets you prove to a client that the contract you audited is exactly the contract that deployed. The proof is a short path through the tree (a Merkle proof), not the whole tree. This is the content addressing → deployment verification story made cryptographically precise and applicable directly to smart contract auditing.

*Branching and merging as language semantics* — git branches are labels pointing to different Merkle roots. If Schematic definitions are Merkle-addressed, branching and merging of code become first-class operations in the language, not in an external version control system. Two versions of a function are two Merkle roots; merging is a tree operation that the language itself can reason about.

**The git comparison:**

| | Git | Merkle Schematic |
|---|---|---|
| Unit of addressing | File | Expression |
| Change detection | File changed | Subexpression changed |
| Deduplication | Identical files | Identical subexpressions |
| Diff granularity | Line | AST node |
| Semantic equivalence | No (bytes only) | Yes (BLC normalization) |
| Branching | External tool | Language primitive |

Git is a Merkle tree over a file system. Merkle Schematic is a Merkle tree over a semantic graph. The semantic version is strictly more powerful because it understands what content means, not just what bytes it contains.

**Implementation:** This is an evolution of the existing content addressing, not a replacement. The change lives entirely in `store.scm` — hash each AST node recursively rather than hashing the whole tree as a flat blob. All existing `hash-of`, `history-of`, `diff`, `same-definition?` semantics are preserved; the Merkle structure adds efficiency and structural sharing on top. The right time to implement this is when writing `store.scm` in Stage 1.

**Interaction with macros:** Macro expansion produces a new AST. The pre-expansion AST and post-expansion AST each get their own Merkle roots. The expansion relationship is stored explicitly — you can `diff` what you wrote against what the macro produced, and you can trace any subexpression in the expanded output back to the macro template that generated it. Content addressing makes macro expansion auditable; Merkle structure makes it efficiently navigable.

### Merkle Graphs in GRASP — The Full Vision and the Pragmatic Fallback

Schematic's Merkle-enhanced ASTs are trees — the standard Merkle construction applies cleanly because ASTs are acyclic and have a single root. GRASP programs are graphs: they have cycles (`¿` back-edges), multiple parents (a node can receive edges from multiple predecessors), and no single root in general. This breaks the standard Merkle construction.

**The full vision: Merkle DAGs with hash-pointer back-edges**

The solution exists in the IPLD (InterPlanetary Linked Data) literature — the same work that underlies IPFS and that Laconic Network's founders contributed to. The construction:

- For acyclic subgraphs (DAGs), hash each node as `hash(node_data, hash(child_1), hash(child_2), ...)` in topological order. This is identical to standard Merkle trees.
- For back-edges created by `¿`, treat the reference as a hash pointer rather than an inline child. The hash of a cycle is `hash(node_data, ..., back-ref=hash(target-node))` — the cycle is broken by pointing to a previously computed hash rather than recursing.

This is semantically clean: `¿i` already means "reference to the earlier node named `i`" — it's a pointer, not a new definition. The hash structure mirrors the semantic structure. Shared subgraphs across different GRASP programs get the same hash. Graph transforms are auditable via pre/post Merkle roots. Incremental recomputation works across graph rewrites.

The three central data structures all use the same mechanism:

| Structure | Topology | Hash treatment |
|---|---|---|
| Schematic ASTs | Trees | Standard Merkle trees |
| GRASP programs | DAGs + cycles | Merkle DAGs + hash-pointer back-edges |
| Petri nets | Bipartite directed graphs | Same as GRASP |

This means `store.scm` is not Schematic-specific — it's a general content-addressed graph store shared by Schematic, GRASP, and the Petri net simulator. One store, three languages, same versioning infrastructure.

**The pragmatic fallback: flat content addressing in GRASP**

Merkle graphs in GRASP are a significant implementation complexity. The cycle-handling, the topological ordering, the IPLD-style hash-pointer representation — these are real engineering work on top of an already ambitious project. The pragmatic fallback, and the recommended implementation order, is:

1. **GRASP uses flat content addressing first** — hash the whole graph as a normalized blob. Every GRASP program gets a single hash identifying it. This gives you semantic identity, deduplication, and the verified deployment story at the program level. It's what the spec originally described and it works.

2. **Merkle structure in GRASP comes later, implemented in GRASP itself** — once GRASP exists and is self-hosting, the Merkle graph enhancement can be implemented as a GRASP program that operates on GRASP graphs. This is the homoiconicity payoff: GRASP manipulating GRASP's own representation, adding Merkle structure to the store from within the language. A GRASP program that takes a flat-hashed graph and produces a Merkle-hashed graph is itself a graph transformation — exactly the kind of thing GRASP should be good at.

3. **Schematic's Merkle trees are the proof of concept** — implementing Merkle trees cleanly in `store.scm` for Schematic ASTs demonstrates the mechanism works. When GRASP is ready, the same design extends to graphs with the back-edge modification. The complexity is additive, not fundamental.

The key insight preserving the fallback's value: **flat content addressing already gives you the most important property — the hash you verified is the hash that runs.** The Merkle structure adds efficiency and subgraph-level granularity on top of that guarantee, but the guarantee itself doesn't require Merkle structure. Start with flat, add Merkle when the foundation is solid.

---

## GRASP — Language Design

### Core Idea

Programs are graphs. Nodes hold computations written in Schematic. Edges define control and data flow. The topology — not just the values — is first-class syntax.

### Node Syntax

```
(name = expr)
```

`name` identifies the node. `expr` is a Schematic expression. `=` is declaration, not assignment. Nodes are immutable once declared.

### Branching Operator: `?`

`?` is the **forward-looking** operator. Declares outgoing edges and branching semantics.

**Built-in edge types:**

| Operator | Semantics |
|---|---|
| `?if` | Conditional branch — one path taken |
| `?par` | Parallel fork — all paths simultaneously (Petri net split) |
| `?net` | Network propagation — weighted edges (neural net style) |
| `?N` | Explicit branch count (e.g. `?3`) |

**User-defined edge types** — `?{symbol}` where symbol is not built-in. Defined via `define-edge-type` in Schematic. New concurrency models are libraries, not language changes.

### Cycle Operator: `¿`

`¿` is the **backward-looking** operator — the visual mirror of `?`. Creates back-edges in the graph.

```scheme
(counter = 0)
    ?seq counter step
(step = (next-or-stop counter 3))   ; returns next value, or false to stop
    ?back step counter               ; ¿ closes the loop
(?seq counter result)
(result = counter)
```

`?` always looks forward. `¿` always looks backward. They are semantic mirrors, visually encoded. `¿` is the only construct that breaks tree structure.

**Execution semantics:** When a `?back` edge fires, the source node's value flows backward to rebind the target node's name in the execution environment. On the next iteration, the target node uses the rebound value instead of re-evaluating its original expression. This is implemented as a graph-level trampoline — the same pattern Stage 0 uses for tail call optimization, but at the graph level rather than the function level.

**The `¿` contract:** The node carrying a `?back` edge is the loop's continuation signal. Its value determines whether the loop continues:
- **Truthy value** → `¿` fires, value flows back to rebind the target, execution restarts from target
- **False/nil** → loop exits, execution continues forward past the back-edge

The idiomatic pattern: the step node returns the next loop variable value if iteration should continue, or `false` when done.

```scheme
; step returns next-val (truthy = continue) or false (stop)
(define (next-or-stop n limit)
  (if (< n limit) (+ n 1) false))

(counter = 0)
    (?seq counter step)
(step = (next-or-stop counter 3))
    (?back step counter)
```

**The structural constraint — `¿` is not `goto`:** A `?back` edge from source to target is only valid if target already has a forward path to source. The back-edge must close an existing cycle — it cannot jump to an unconnected node. This is enforced at runtime by `validate-back-edges` before evaluation begins, and will be enforced statically at compile time.

```
Valid:   counter → step → ?back→ counter   (step reachable from counter ✓)
Invalid: a → b,  island → ?back→ island    (island has no path to b ✗)
```

This is the difference between structured and unstructured jumps. `¿` is powerful — like `goto`, the developer is responsible for loop termination — but it cannot jump to structurally unrelated nodes.

**Loop body as a first-class concept:** Given a `?back` edge, the loop body is the intersection of nodes reachable forward from target and nodes that can reach source backward. This is computable, inspectable, and content-addressable — the loop body is not implicit syntax but an explicit subgraph you can query and formally verify.

### Example: Neural Network Layer

```
(input = x)
    ?net (hidden = relu(h))
             ?net (output = softmax(o))
```

Each `?net` is a matrix multiplication with learned weights. The graph topology IS the network architecture. `?net` with a sparse adjacency matrix is naturally sparse attention.

### Graphs as Adjacency Matrices

Any GRASP graph maps to an adjacency matrix where `[i][j]` is the edge weight from node i to node j:

- `?par` → block-diagonal matrices (independent parallel computations)
- `?net` → dense weight matrices (neural network layers)
- `?if` → sparse 0/1 matrices (conditional routing)

The runtime chooses between graph traversal (small/sparse) and matrix multiplication (large/dense/GPU). The user writes topology; the system picks the representation. GRASP programs can be handed to NumPy/PyTorch/XLA as tensors — the graph IS the tensor computation.

### Formal Verification: Petri Nets + TLA+

**GRASP is a verifiable language.**

Petri nets and TLA+ (Leslie Lamport's specification language, used by AWS, Microsoft, Intel) are both formal models for concurrent systems and equivalent for a large class of problems. GRASP programs compile mechanically to TLA+ specs:

- Places → state variables (token counts)
- Transitions → actions (enabled when input places have tokens)
- `?par` → parallel enabled transitions
- `¿` → cycles in the state space

**Properties become Schematic code:**

```scheme
(define-property no-deadlock
  (always (some-transition-enabled)))

(define-property terminates
  (always-eventually (transition-fires exit)))
```

**The compilation pipeline:**

```
GRASP source
    ↓
TLA+ spec (automatic, mechanical)
    ↓
TLC model checker
    ↓
Passes → compile to WASM
Fails  → counterexample shown in GRASP syntax
```

**What nobody has built:** most languages with formal verification (Rust, LiquidHaskell, Dafny) verify *sequential* properties — type safety, memory safety. GRASP verifies *concurrent* properties — deadlock freedom, liveness under all interleavings — because the concurrency model (Petri nets) is the same formalism as the analysis tool. The model checker is part of the compilation pipeline, not a separate tool.

**Colored Petri nets + liquid types:** Liquid types on tokens — `{x : Int | x > 0}` — let the model checker verify type invariants across all reachable states. Value-level safety + concurrency safety + exhaustive verification, all in one system. This is novel — no existing general-purpose language does this.

### Consensus Algorithms in GRASP

GRASP's `?par`/`¿` model naturally expresses distributed consensus. Leader election, voting rounds, and retry loops all map to graph topology. Deadlock detection and liveness are questions about graph structure — statically checkable at compile time. A genuine research contribution: consensus correctness verified by the runtime, not just provable on paper.

---

## Memory Management

### The Approach: Linear Types from Petri Net Semantics

GC pauses are unpredictable. For real-time systems, "fast on average" is not good enough. Petri net tokens are naturally linear — consumed exactly once. This maps directly to ownership semantics without a borrow checker:

**Phase 1:** Reference counting for single-threaded use. Immutable data can't form cycles, so simple refcounting works. No pauses.

**Phase 2:** Region inference for function-local allocations. Stack-allocate values that don't escape their scope.

**Phase 3:** Linear types for Petri net tokens. The compiler proves every path that allocates also frees, and nothing uses freed memory.

**Phase 4:** WASM linear memory for hot paths. No GC overhead on the critical path.

This gives C-like performance with static safety — without Rust's annotation burden, because ownership falls out of the execution model rather than being imposed on top.

---

## Compilation Stack

```
GRASP/Schematic source
    ↓  Stage 0 (Python tokenizer + parser)
SList AST
    ↓  Stage 1 (schematic.scm evaluator)
Values / expanded macros
    ↓  BLC normalization (normalize → hash → verify)
BLC terms  ←──── content addressing lives here
    ↓
    ├── WASM         → browser / portable (1.3–2× C++)
    ├── LLVM IR      → native x86/ARM/RISC-V (1.05–1.3× C++)
    ├── XLA HLO      → GPU/TPU (not C++, matrix ops at 300+ TFLOPS)
    ├── TLA+         → formal verification output
    └── RISC-V VM    → blockchain / embedded
```

**BLC as universal IR:** Binary Lambda Calculus normalization solves the N×M backend problem. Two functions computing the same thing normalize to the same BLC term — same hash. One frontend, N backends, N+1 compilers instead of N×M.

---

## Roadmap

### Phase 1 — Stage 0 Complete ✅

| Feature | Status |
|---|---|
| Core evaluator | ✅ |
| Pattern matching (with quoted symbol literals) | ✅ |
| Hygienic macros (full auto-renaming) | ✅ |
| Sweet expressions | ✅ |
| Module system (require/provide) | ✅ |
| Content addressing (hash-of, history-of, diff) | ✅ |
| Python FFI | ✅ |
| Rest params | ✅ |
| Mutable boxes | ✅ |
| TCO (100k+ depth) | ✅ |
| Error messages with line numbers | ✅ |
| REPL with readline, highlighting, history | ✅ |
| Meta-circular evaluator (mce.scm, ~300 lines) | ✅ |
| 136 tests passing | ✅ |

### Phase 2 — Stage 1: Schematic in Schematic

Order matters — each depends on the previous:

**1. `stdlib.scm`** (~1-2 days) — move prelude out of Python, add `group-by`, `frequencies`, `partition`, `flat-map`, `reduce`, `sort-by`, `take-while`, `drop-while`, `str-contains?`, `number->string`.

**2. `test.scm`** (~2-4 hours) — test runner macro. Content-addressed test identity: the hash of a test definition IS its identity. Rerunning unchanged tests is optional.

**3. `store.scm`** (~1-2 days) — content addressing logic in pure Schematic. SHA-256 via FFI, everything else in `.scm`. This is where Merkle-enhanced AST hashing gets implemented — hash each node recursively as `hash(node_type, hash(child_1), ...)` rather than hashing the whole tree flat. Adds incremental verification, structural sharing, cheap diffs, and the foundation for distributed code sharing. See the Merkle-Enhanced ASTs section in Content Addressing.

**4. `match.scm`** (~1-2 weeks, the hard one) — pattern matching as a macro. A `match` expression compiles to nested `if`/`cond` chains. This is what Racket's `match` does. Complex but well-understood.

**5. `hygiene.scm`** (~1 week) — the auto-renaming engine in Schematic. Walks macro templates, identifies introduced symbols, renames them. Depends on `match.scm`.

**6. `modules.scm`** (~2-4 days) — `require`/`provide` policy in Schematic. Python handles file I/O; this handles what gets exported and how names are resolved.

**7. `repl.scm`** (~2-4 days) — REPL loop, command dispatch, paren tracking, display. Python handles `input()` and readline; this handles everything above that.

**8. `schematic.scm`** — requires 1-7. The complete Stage 1 interpreter. Extends `mce.scm` with all missing features.

### Phase 3 — WASM Backend

`Schematic AST → BLC terms → WASM bytecode`. Reference: Guile Hoot (Scheme→WASM).

### Phase 3.5 — Petri Net Simulator in Schematic

Before implementing GRASP, build a Petri net simulator as a standalone Schematic program. This serves three purposes: it validates the formal model that GRASP is built on, it produces something immediately useful and demonstrable, and it forces the design of the `?par`/`¿` execution semantics before committing to syntax.

```
petri.scm        — core net: places, transitions, markings, firing rules
petri-viz.scm    — text visualization of net state
petri-verify.scm — deadlock detection, boundedness, liveness checking
petri-tla.scm    — emit TLA+ specs from net definitions
```

**What a Petri net in Schematic looks like:**

```scheme
(require "petri.scm")

; Define a simple producer-consumer net
(define producer-consumer
  (make-net
    :places      '(ready  producing  buffer  consuming  done)
    :transitions '((produce :from '(ready)     :to '(producing))
                   (fill    :from '(producing) :to '(buffer))
                   (consume :from '(buffer)    :to '(consuming))
                   (finish  :from '(consuming) :to '(done ready)))))

; Initial marking — one token in 'ready
(define m0 (marking '((ready . 1))))

; Run the simulator
(define result (simulate producer-consumer m0 :steps 10))

; Verify properties
(deadlock-free? producer-consumer m0)  ; => true
(bounded? producer-consumer m0 3)      ; => true
(can-reach? producer-consumer m0 '((done . 1))) ; => true
```

**Why this before GRASP:** GRASP's `?par` is syntactic sugar for a Petri net transition. `¿` is a back-edge creating a cycle in the reachability graph. Building the simulator first means the GRASP compiler has a clean semantic target — it translates `?par` nodes to `(make-transition ...)` calls, and the simulator handles execution. The TLA+ emission in `petri-tla.scm` is the formal verification backend for GRASP programs.

This is also the most immediately publishable piece — a Petri net DSL in Schematic with automatic TLA+ generation is a self-contained research contribution before GRASP exists.

### Phase 4 — GRASP Implementation

GRASP parser, graph IR, `?if`/`?par`/`?net` evaluator, adjacency matrix compiler, TLA+ backend, `define-edge-type`.

---

## Potential Applications

### ETL / Data Cleaning DSL

The most immediately practical. Schema mapping (rate cards, healthcare claims, PUDL energy data) is declarative, pattern-heavy, and rule-based — exactly where a Lisp DSL beats Python.

```scheme
(define clean-customers
  (pipeline
    (fill-null :age     from: :median)
    (keep-if   :age     (? positive?))
    (transform :name    (compose str-title str-trim))))
```

Transformations are data — inspectable, testable, content-addressed. Every pipeline step is auditable by hash.

### Content-Addressed Package Registry

"GitHub for Schematic." Dependencies are hashes. `#941e639277ae` cannot change. Supply chain attacks impossible. Semantic deduplication — same implementation, same hash, anywhere. With WASM: publish a hash, run anywhere.

### Smart Contract Language

Structurally better than Solidity: immutable data by default (reentrancy bugs impossible), liquid types (prove invariants before deployment), content addressing (code you audit is provably code that runs), formal verification via TLA+ (liveness and safety at compile time).

Realistic path: compile Schematic to EVM, NEAR WASM, or Polkadot. Not a new blockchain — a better contract language on existing infrastructure.

### Content-Addressed Web Archive

A distributed alternative to the Internet Archive (currently under legal and funding pressure). Content-addressed crawling hashes what it finds — tamper-evident by construction. Deep web via Playwright FFI, Tor via stem FFI. Verifiable: prove a page said X on date Y via the hash. Decentralized: any node with a hash can serve the content.

### Game Scripting / Logic Layer

The Naughty Dog GOAL model: GRASP for game logic, native C++ for rendering. Faster than Lua (linear memory, no GC pauses), safer than everything (deadlock impossible by construction), deterministic (immutable data + Petri net execution = lockstep multiplayer). Content-addressed mods: every game asset identified by hash, no version conflicts.

### ML Architecture Description

GRASP as an architecture description language compiling to PyTorch/JAX. `?net` is matrix multiplication with learned weights. Graph topology = network architecture, explicitly. Architectural verification catches residual connection bugs before training. Content-addressed architecture search: every architecture you've tried, stored by hash with training results.

### LLM-Native Language

As LLM-assisted development becomes the norm, languages that make LLM-generated code verifiable become more valuable. The compiler becomes the adversarial verifier of LLM output. Immutable data eliminates state tracking errors. Explicit topology matches how LLMs represent relationships internally. Content addressing solves context window navigation — fetch any definition by hash.

---

## Monetization

**Consulting** — the skills demonstrated here (compiler design, formal verification, distributed systems) are rare and billable. Immediate.

**Smart contract verification service** — charge per verification or subscription. The language is the moat; the service is the revenue. Smart contract auditing firms charge $50-200k per audit.

**ETL tooling as SaaS** — $500-2000/month per team. Most tractable near-term product.

**Conference circuit** — StrangeLoop, FOSDEM, Lambda World, Devcon. Language designers become known through talks. Publish at ICFP, PLDI, or CAV first.

**Acquisition / hiring** — Ethereum Foundation, Anthropic, Jane Street, ML infrastructure companies.

---

## Design Decisions

**Immutable by default** — race condition safety without a borrow checker. Maps to WASM. Enables content addressing.

**Sweet expressions** — parentheses were never load-bearing. Homoiconicity preserved.

**`?`/`¿` as mirrors** — forward fork / backward join. Syntax-level topology is the innovation.

**Extensible edge types** — new concurrency models are libraries, not language changes.

**BLC as IR** — content addressing for free from normalization. Same algorithm = same hash.

**Linear types from Petri net semantics** — ownership falls out of the execution model. Not imposed on top.

**Self-hosting as design goal** — if Schematic can't express its own semantics, the design has a gap. The Stage 1 `.scm` files are the test.

---

## File Structure

```
; Stage 0 — Python scaffold
schematic.py              Interpreter (~2,500 lines, shrinking toward ~800)
test_schematic.py         136 tests, all passing

; Stage 1 — Schematic in Schematic (core)
mce.scm                   Meta-circular evaluator (~300 lines) ✅
stdlib.scm                Standard library (planned)
test.scm                  Test runner macro (planned)
store.scm                 Content addressing + Merkle AST hashing (planned)
match.scm                 Pattern matching as a macro (planned)
hygiene.scm               Hygienic macro expansion (planned)
modules.scm               require/provide logic (planned)
repl.scm                  REPL loop (planned)
schematic.scm             Complete Stage 1 interpreter (planned)

; Stage 1 — Standard libraries (planned, post-core)
math.scm                  Math functions, number theory, statistics
string.scm                String utilities beyond stdlib basics
io.scm                    File I/O, streams, ports
vcs.scm                   Git integration + semantic VCS operations
blame.scm                 Expression-level provenance (who wrote what, when)
sync.scm                  Distributed definition sharing via Merkle transfer
release.scm               Semantic versioning, changelog generation

; Stage 3.5 — Petri net simulator (planned)
petri.scm                 Core net: places, transitions, markings, firing rules
petri-viz.scm             Text visualization of net state
petri-verify.scm          Deadlock detection, boundedness, liveness checking
petri-tla.scm             Emit TLA+ specs from net definitions

; Smart contract auditing tool (planned)
solidity-ast.scm          Consume solc AST JSON, extract state/transitions
solidity-petri.scm        Map Solidity control flow to Petri net
solidity-verify.scm       Run TLC, parse counterexamples, format findings
```

---

## Standard Library Philosophy

These libraries represent things that should be fundamental and universal but mysteriously aren't included in most languages. The design principle: if a developer has to reach for a third-party package for something this basic, the language has failed them.

### `math.scm`

Beyond the basics (`+`, `-`, `*`, `/`, `mod`, `abs`, `min`, `max`):

```scheme
; Number theory
(gcd 12 8)          ; => 4
(lcm 4 6)           ; => 12
(prime? 17)         ; => true
(factors 12)        ; => (2 2 3)
(primes-up-to 20)   ; => (2 3 5 7 11 13 17 19)

; Statistics
(mean '(1 2 3 4 5))      ; => 3
(median '(1 2 3 4 5))    ; => 3
(std-dev '(1 2 3 4 5))   ; => 1.414...
(percentile 90 data)

; Numeric utilities
(clamp 0 100 x)      ; keep x in [0, 100]
(lerp 0.0 1.0 0.5)   ; linear interpolation => 0.5
(approximately= 1e-9 a b)  ; float comparison with epsilon
```

### `string.scm`

```scheme
(str-split "hello world" " ")   ; => ("hello" "world")
(str-join '("a" "b" "c") ", ") ; => "a, b, c"
(str-pad "hi" 10 :right)        ; => "hi        "
(str-trim "  hello  ")          ; => "hello"
(str-contains? "hello" "ell")   ; => true
(str-replace "hello" "l" "r")   ; => "herro"
(str-starts-with? "hello" "he") ; => true
(str-format "~a is ~a" name age) ; template formatting
```

### `vcs.scm` — Git Integration with Semantic Awareness

The key insight: most languages treat version control as an external tool. Schematic treats it as a first-class language concern because the Merkle store and git's object model are the same structure at different granularities. `vcs.scm` bridges them.

```scheme
(require "vcs.scm")

; Standard git operations via FFI
(vcs-status)
; => ((modified "stdlib.scm") (untracked "petri.scm"))

; Semantic status — what actually changed at expression level
(vcs-semantic-status)
; => ((changed square "941e63" "20d4ed")
;     (added   make-net "7f3a91")
;     (unchanged map filter fold))

; Commit with Merkle root attached as metadata
(vcs-commit "add Petri net simulator"
  :semantic-root (current-merkle-root))

; Checkout a past version of one definition without touching anything else
(vcs-definition-at "941e639277ae" square)
; => the original square function, without checking out any git branch

; What changed in a definition between two commits
(vcs-definition-diff "HEAD~1" "HEAD" square)
; => (body-changed (* x x) → (+ x x))
```

### `blame.scm` — Expression-Level Provenance

Git blame tells you which commit last touched a line. `blame.scm` tells you which commit introduced a specific subexpression — the granularity matches the actual unit of meaning.

```scheme
(require "blame.scm")

; When was this exact subexpression introduced?
(blame-expression square '(* x x))
; => (commit "a3f9b2" author "you" date "2026-03-01"
;     message "initial square implementation")

; Full history of a definition
(blame-definition make-net)
; => list of (commit, version, change-description) for every change

; Who introduced a specific pattern anywhere in the codebase?
(blame-pattern '(if (null? _) _ _))
; => all definitions containing this pattern with their provenance
```

### `release.scm` — Semantic Versioning

Semantic versioning done properly: version bumps derived from what actually changed, not from what a human decided to call it.

```scheme
(require "release.scm")

; What changed since the last release?
(release-diff "v0.1.0")
; => ((breaking  remove-function old-api)
;     (changed   square "941e63" → "20d4ed")
;     (added     petri-net-simulator))

; Suggest the correct semver bump
(suggest-version "v0.1.0" (release-diff "v0.1.0"))
; => "v0.2.0"  ; public API changed → minor bump
; not "v0.1.1" — that would be wrong

; Generate a changelog from semantic diff
(generate-changelog "v0.1.0")
; => markdown with definition names, hashes, change descriptions
```

### `sync.scm` — Distributed Definition Sharing

Content-addressed definitions can be shared by hash rather than by package name and version. This is the foundation of the package registry idea — not a centralized server, just Merkle transfer between peers.

```scheme
(require "sync.scm")

; Share a definition — anyone with this URI gets exactly this implementation
(publish-definition square)
; => "schematic://941e639277ae"

; Fetch by hash — verified on arrival
(fetch-definition "schematic://941e639277ae")
; => the square function, hash verified

; Sync only what changed — like git fetch but for expressions
(sync-with peer-address :since last-sync-root)
; => transfers only the Merkle subtrees that differ
```

### Why These Belong in the Language

The reason these aren't in most languages is historical accident — languages were designed when disk space was expensive, standard libraries were minimal, and "batteries included" wasn't a goal. The consequence is that every project re-implements string splitting, every team picks a different math library, and version control is universally treated as someone else's problem.

For Schematic specifically, `vcs.scm` and `blame.scm` aren't optional add-ons — they're the natural completion of the content addressing story. A language with a Merkle-addressed AST store that doesn't expose VCS integration is leaving the most useful interface to that store unused. The Merkle store IS a version control system for expressions; `vcs.scm` just makes it talk to the filesystem version control system developers already use.

---

## Speculative Research Directions

*These ideas emerged from design discussions and are flagged as potentially novel or worth pursuing. They are not part of the current implementation and range from "probably correct and worth doing" to "speculative but interesting." Each connects to the core graph homoiconicity thesis in a different way.*

---

### Continuations as Backpropagation

**The idea:** Reverse-mode automatic differentiation (backpropagation) is structurally identical to continuation-passing style transformation. The backward pass IS the continuation of the forward pass. In a language with first-class continuations, you can implement backprop by capturing the continuation at each operation, then running the continuations in reverse order during the backward pass — no separate "tape" or computation graph needed.

**Prior art:** Pearlmutter and Siskind (2008) proved this mathematically. JAX's `grad` transformation is a partial realization. This is not a new mathematical observation.

**What GRASP adds:** In current languages this is an implementation trick — something the runtime does under the hood. In GRASP it becomes explicit in the syntax. The forward pass follows `?` edges. The backward pass follows `¿` edges — the same graph traversed in reverse. If `?net` means "propagate forward through this weighted edge," then `¿net` means "propagate gradients backward through this weighted edge," which is exactly the chain rule.

Backpropagation isn't a separate algorithm in GRASP — it's the `¿` operator applied to `?net` graphs. The `?`/`¿` symmetry that the language already has for graph traversal is mathematically the same symmetry as forward/backward pass in differentiation. This isn't just an analogy — it's the same underlying structure.

**The novel combination:** Graph transforms (macros) + differentiable execution. A graph transform macro that takes the current computation graph and returns a modified graph, where the gradient signal informs the transform. Not just "update these weights" but "restructure this subgraph." The architecture becomes part of the differentiable computation. This is the direction Neural Architecture Search points toward but can't quite reach — GRASP would make continuous architecture optimization natural because the architecture and the computation are both GRASP graphs.

**For LLM reasoning:** A reasoning trace is a graph. A graph transform is a program that rewrites reasoning traces. Gradient feedback could flow backward through the trace via `¿` edges, and a graph transform could then restructure the reasoning strategy. The meta-level (rewriting strategy) and object-level (reasoning trace) are both GRASP graphs, both differentiable, both content-addressed. This is a novel research direction — not known to be pursued elsewhere in this form.

**Status:** Mathematically sound, unimplemented, connection to GRASP syntax is genuine not metaphorical. The `?net`/`¿net` symmetry for backprop deserves a formal writeup.

---

### Content Addressing Makes Graph Transforms Safe

**The idea:** The main argument against Lisp macros — and by extension against GRASP graph transforms — is that they can modify code into something dangerous and irrecoverably different from what you wrote. Content addressing solves this: every transformation has a hash of what went in and a hash of what came out. You can diff them, revert them, inspect them.

This is not just a code management feature. It's a *safety guarantee for metaprogramming*. Macro expansion is auditable. Graph rewrites are traceable. The transformation history is content-addressed, which means every version is retrievable and comparable.

**The verification connection:** TLA+ verification of a GRASP program is only meaningful if you can prove that the program you verified is the program that runs. Content addressing gives that guarantee — the hash you verified is the hash that executes. Most formal methods work verifies a *description* of a program, not the program itself. Content addressing closes that gap.

**Status:** This is one of the core design insights of the project, now stated precisely. Should be in every public description of the language.

---

### DSL Universality Through Graph Restriction

**The idea:** Every other data structure is a special case of a graph. Therefore, every paradigm built on a specific data structure is a special case of GRASP:

- A list is a path graph. Restrict GRASP to path-graph topology with `?seq` edges → you have Lisp. Lisp is a DSL in GRASP.
- A stack is a list with restricted access. Define push/pop as edge types → Forth is a DSL in GRASP.
- An array is a path graph with indexed access. A matrix is a 2D grid graph. Define `?net` edges with dense weight matrices → APL-style array programming is a DSL in GRASP.
- A state machine is a graph where nodes are states and edges are transitions — directly GRASP.
- A dataflow graph is what `?par` describes.

**The strong claim:** In GRASP, the DSL's data structure and the DSL's execution model are both expressible as graphs, so the DSL is homoiconic with the host language. A Lisp DSL in GRASP isn't a library that interprets lists — it IS a graph with list topology, and GRASP can manipulate, verify, and content-address it natively.

The question of which language paradigm is "best" dissolves — they're all views of the same underlying structure, derivable by restricting the graph topology.

**Status:** Mathematically sound. Whether GRASP's specific syntax supports this elegantly in practice is the central open question (see: "Can homoiconicity work with graphs?"). This is the claim that most needs empirical validation through implementation.

---

### LLM Reasoning as Inspectable Graph

**The idea:** Current LLM reasoning is linear — token by token, which is a path graph. Even chain-of-thought is sequential. Expressing reasoning as a GRASP graph would enable:

- `?par` for genuine parallel hypothesis tracking (addressing premature commitment failure mode)
- `¿` for explicit backtracking to named reasoning nodes (currently impossible in standard generation)
- Named, content-addressed reasoning steps (every intermediate conclusion has a hash)
- Causal tracing as a graph reachability query
- Reproducibility: two reasoning traces that differ at one node have different hashes from that node forward

**The near-term version:** Use GRASP as a reasoning trace *format* that an LLM outputs, where the structure is explicit and content-addressed. Not the model running GRASP, but the model generating GRASP as its chain-of-thought. The reasoning graph becomes an artifact that can be inspected, verified, and content-addressed, even if the model that generated it is a standard transformer.

**Status:** Speculative about the benefits, but the inspectability argument is solid regardless of whether structured reasoning generation improves accuracy. The auditability gains are real.

---

### Liquid Types + Content Addressing = Search by Contract

**The idea:** In a content-addressed language, a function's identity is the hash of its implementation. If liquid types are added, a function's type includes its behavioral contract — `sort : List a -> {xs : List a | isSorted xs}`. If the type annotation becomes part of what gets hashed, you can look up a function not just by what it *does* but by what it *guarantees*.

This enables: a content-addressable library where you search by behavioral contract, not name. "Find me a function that takes an unsorted list and returns a sorted one, provably" is a precise query.

**Status:** Liquid types not yet implemented. The combination with content addressing is novel and practically useful. Worth pursuing once liquid types are added.

---

### Session Types for Petri Net Concurrency

**The idea:** Liquid types reason about value properties. Petri net execution needs to reason about different things — which places have tokens when, whether a transition can ever fire, whether the net can deadlock. The resolution is a two-layer type system: liquid types for value-level properties, session types for concurrency properties (who sends what to whom, in what order).

Combining liquid types (value properties) with session types (communication properties) over a Petri net execution model would be genuinely novel and theoretically sound. Session types are what linear types are to memory, applied to communication.

**Status:** Research program, not near-term implementation. Identified as the right theoretical direction for typing the concurrency model.

---

*These directions are recorded here to preserve the ideas and establish priority. The core project is the implementation of graph homoiconicity — these are downstream consequences and extensions that become relevant once the foundation works.*

Paste this document, then say:

> "I'm continuing work on Schematic and GRASP. The architecture has three stages: Stage 0 is a Python interpreter (~2,500 lines, 136/136 tests passing) providing the irreducible bootstrap — tokenizer, parser, trampoline, FFI. Stage 1 is Schematic written in Schematic — the meta-circular evaluator (`mce.scm`, ~300 lines) is done and proves it's possible. The next Stage 1 files are `stdlib.scm`, `test.scm`, `match.scm`, `hygiene.scm`, `modules.scm`, `repl.scm`, and finally `schematic.scm` — the complete interpreter in Schematic. Stage 2 is the WASM backend. Current priority: `stdlib.scm`."

---

*Last updated: March 2026*
*Stage 0: Python 3.11+, ~2,500 lines, 136/136 tests*
*Stage 1: mce.scm complete, rest planned*
*Stage 2: Not started*
*GRASP: Design complete, implementation not started*
