---
name: tax-architecture
description: The calculation-graph architecture for the deterministic tax engine - node identity, evaluation, provenance records, rounding, constants and UnsupportedItem. Read before writing or changing any engine code, any form line, or anything under backend/app/services/tax_engine/.
---

How the deterministic engine is built. This is the contract `/implement-form`
builds against and `/trace-check` verifies.

## The shape

```
TaxpayerFacts ──► graph of Nodes ──► ReturnResult
   (typed)          (one per form line)   (every line, each with a NodeResult)
```

One node per line of one form. A node declares what it needs, computes from
nothing else, and returns a figure plus the record of how it got there. No node
reads a database, calls a model, touches the network, or looks at global state.
Given the same `TaxpayerFacts` the graph returns the same `ReturnResult`, on any
machine, forever - that is the whole reason this layer exists, and it is what
lets a review say "the tax is wrong" rather than "the tax is different today".

## Node identity

`<form>.l<line>`, lowercase, no padding, the line number exactly as the form
prints it:

```
f1040.l11        Form 1040 line 11
f1040.l6b        a lettered sub-line stays lettered
sch1.l8z         Schedule 1 line 8z
scha.l5e         Schedule A line 5e
schd.l16         Schedule D line 16
f8949.p1.l2h     a form with numbered parts carries the part
f8889.l13
qdcgtw.l25       Qualified Dividends and Capital Gain Tax Worksheet
schdtw.l45       Schedule D Tax Worksheet
il1040.l11       state forms use the state's own form name
schicr.l10
schilwit.l4
```

Two other kinds of leaf:

```
facts.wages              a figure read off a document
const.2025.std_ded_mfj   a figure fixed by an authority
```

The id is a public identifier: it goes in the provenance record, in the
calculation report, in `explain(node_id)`, and into the UI's drill-down. Renaming
one is a breaking change. Worksheets get ids on the same footing as forms,
because Basic 5 reconciles only through the Tax Table and CS 2 only through
Form 7203 - a worksheet that is not a node is a figure with no provenance.

## Node

```python
@dataclass(frozen=True, slots=True)
class Node:
    id: str
    form: str
    line: str
    label: str                        # the form's own wording for the line
    inputs: tuple[str, ...]           # node ids, declared not discovered
    compute: Callable[[Resolved], Decimal]
    authority: str                    # key into tax_authority, or ""
    rounding: Rounding = Rounding.NONE
```

`inputs` is declared rather than inferred from the body. It is what makes the
graph a graph: the topological order, the cycle check, `derived_from`, and the
drill-down tree all come from it. A `compute` that reaches a figure not in its
own `inputs` is the defect this design exists to make impossible - it is how a
line ends up correct on the sample that was tested and wrong on the next one,
with a provenance record that says otherwise.

## Evaluation

Resolve in topological order, memoised, once per return. A cycle is a build-time
error, not a runtime one: assert acyclicity when the graph is assembled, not
when a taxpayer's facts arrive. Evaluating a node produces its result and its
provenance in the same step - never a second pass that reconstructs the
reasoning, because a reconstruction can disagree with what actually ran and it
will read as evidence when it does.

```python
@dataclass(frozen=True, slots=True)
class NodeResult:
    node_id: str
    amount: Decimal
    formula: str                      # the arithmetic with operands substituted
    inputs: tuple[tuple[str, Decimal], ...]
    authority: Authority | None
    sources: tuple[SourceFact, ...]   # empty unless this is a facts.* leaf
    basis: str                        # extracted | computed | statutory | flagged
    flags: tuple[str, ...] = ()
```

`formula` carries the numbers, not the symbols: `"7,410 + 1,236 = 8,646"`, not
`"a + b"`. A reader checking a return in their hand cannot use the second one.

`SourceFact` is the other half of Phase 3 and carries document, page, field,
confidence and bounding box where OCR gave one. Per trap 34, the document on a
fact is the document that *reported* it - not `documents[0]`, not the first row
an unordered query returned. That field decides which page the UI opens and
which page's OCR confidence flags the figure, and getting it wrong flagged 84
clean figures on Basic 7.

## Money and rounding

`Decimal` everywhere, never `float`. Serialize as string.

Round only where the form's own instructions say to round, declared per node as
`rounding=`. Never round mid-computation and then again at the end: the 1040
rounding rule applies to entries, so a worksheet that feeds a line keeps its
cents until the line it feeds is entered. `ROUND_HALF_UP` where the IRS says
"round .50 and up to the next dollar" - not Python's default banker's rounding,
which is a different answer on exactly the figures a reviewer spot-checks.

## UnsupportedItem

A node raises `UnsupportedItem` when the facts contain something it cannot
compute. Never approximate, and never return zero - zero in a money column is
itself a figure, which is trap 32.

What happens next is a deliberate reading of two rules that pull against each
other. The plan says unsupported situations raise; the owner's standing
instruction and trap 30 say a flagged return beats no return, because a preparer
cannot correct a return that does not exist. So:

- the raising node's result is `basis="flagged"` with the unsupported reason,
- every node downstream of it inherits an `unsupported` flag,
- **the rest of the return still computes**,
- the `ReturnResult` is marked not fileable, naming the lines that are
  unsupported and why,
- and a review item is raised per unsupported line.

Approximation never happens in either reading. If you are about to widen this -
to refuse the whole return, or to let an unsupported line pass silently - that
is a decision for the user, and `docs/refactor-plan.md` lists it as open.

## Constants

Figures come from `tax_authority.py`, which already pairs each value with its
`Authority` and a `verified` flag, and which `tax_tables` derives from. Do not
write a number into a node body, and do not add a second place a figure can come
from. A constant you could not confirm against primary text is `verified=False`;
the engine surfaces those rather than filing on them.

2025 has two layers and a constant that acknowledges one is wrong in the way
hardest to spot: Rev. Proc. 2024-40 set the inflation adjustments, and the One
Big Beautiful Bill Act (Pub. L. 119-21) then superseded several of them.

## The module this replaces

`calculation_trail.py` builds a `TrailRow` per line by hand - source, formula,
authority, `feeds_into`, `derived_from`, `basis` - which is most of `NodeResult`
assembled in a parallel structure that can drift from the computation. Its
`verify(rows, result)` recomputes each row against the engine and returns the
disagreements.

During the migration, keep it: build the trail from evaluated `NodeResult`s and
run `verify` against the old engine on CS 2 and Basic 5. A form is migrated when
the graph and the old path agree to the cent on both, and `verify` returns
empty. `feeds_into` is the only field the graph does not give you directly -
derive it by inverting `inputs` across the whole graph, once, at assembly.

## What never goes in a node

No LLM call - the model extracts and proposes, this layer computes, and any
model figure disagreeing beyond `CALC_TOLERANCE_DOLLARS` becomes a review item
with the deterministic value winning. No network, no session, no clock, no
environment read, no logging of a value. A node that needs the current date
takes it as a fact.
