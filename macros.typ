// Reusable notation, environments, and formatting helpers.

// ---------- Blackboard Bold ----------
#let bbA = $bb(A)$
#let bbB = $bb(B)$
#let bbC = $bb(C)$
#let bbD = $bb(D)$
#let bbE = $bb(E)$
#let bbF = $bb(F)$
#let bbG = $bb(G)$
#let bbH = $bb(H)$
#let bbI = $bb(I)$
#let bbJ = $bb(J)$
#let bbK = $bb(K)$
#let bbL = $bb(L)$
#let bbM = $bb(M)$
#let bbN = $bb(N)$
#let bbO = $bb(O)$
#let bbP = $bb(P)$
#let bbQ = $bb(Q)$
#let bbR = $bb(R)$
#let bbS = $bb(S)$
#let bbT = $bb(T)$
#let bbU = $bb(U)$
#let bbV = $bb(V)$
#let bbW = $bb(W)$
#let bbX = $bb(X)$
#let bbY = $bb(Y)$
#let bbZ = $bb(Z)$

// ---------- Calligraphic ----------
#let cA = $cal(A)$
#let cB = $cal(B)$
#let cC = $cal(C)$
#let cD = $cal(D)$
#let cE = $cal(E)$
#let cF = $cal(F)$
#let cG = $cal(G)$
#let cH = $cal(H)$
#let cI = $cal(I)$
#let cJ = $cal(J)$
#let cK = $cal(K)$
#let cL = $cal(L)$
#let cM = $cal(M)$
#let cN = $cal(N)$
#let cO = $cal(O)$
#let cP = $cal(P)$
#let cQ = $cal(Q)$
#let cR = $cal(R)$
#let cS = $cal(S)$
#let cT = $cal(T)$
#let cU = $cal(U)$
#let cV = $cal(V)$
#let cW = $cal(W)$
#let cX = $cal(X)$
#let cY = $cal(Y)$
#let cZ = $cal(Z)$

// ---------- Math Operators ----------
#let argmax = math.op("arg max")
#let argmin = math.op("arg min")
#let rank = math.op("rank")
#let trace = math.op("tr")
#let diag = math.op("diag")
#let span = math.op("span")
#let supp = math.op("supp")
#let dom = math.op("dom")
#let codom = math.op("codom")
#let img = math.op("im")
#let ker = math.op("ker")

// ---------- Probability ----------
#let Pr = math.op("Pr")
#let EE(x, given: none, measure: none) = {
  let op = if measure == none { $op("E")$ } else { $op("E")_#measure$ }
  if given == none {
    $#op lr([#x])$
  } else {
    $#op lr([#x | #given])$
  }
}
#let Var(x, given: none, measure: none) = {
  let op = if measure == none { $op("Var")$ } else { $op("Var")_#measure$ }
  if given == none {
    $#op lr([#x])$
  } else {
    $#op lr([#x | #given])$
  }
}
#let Cov(x, given: none, measure: none, ..args) = {
  let pos = args.pos()
  if args.named().len() > 0 {
    panic("Cov received unexpected named arguments")
  }
  let op = if measure == none { $op("Cov")$ } else { $op("Cov")_#measure$ }
  if pos.len() == 0 {
    if given == none {
      $#op lr([#x])$
    } else {
      $#op lr([#x | #given])$
    }
  } else if pos.len() == 1 {
    let y = pos.at(0)
    if given == none {
      $#op lr([#x, #y])$
    } else {
      $#op lr([#x, #y | #given])$
    }
  } else {
    panic("Cov accepts at most two positional arguments")
  }
}

// ---------- Delimiter Helpers ----------
#let abs(x) = $lr(|#x|)$
#let norm(x) = $lr(||#x||)$
#let inner(x, y) = $angle.l #x, #y angle.r$
// Typst reserves `set` as a keyword, so the set-builder helper is named `setof`.
#let setof(x) = $lr({#x})$
#let ceil(x) = $lr(ceil.l #x ceil.r)$
#let floor(x) = $lr(floor.l #x floor.r)$

// ---------- Callouts ----------
#let callout(title, body, fill) = block(fill: fill, inset: 10pt, radius: 5pt, width: 100%)[
  *#title*

  #body
]
#let note(body) = callout("Note.", body, rgb("#eef6ff"))
#let warning(body) = callout("Warning.", body, rgb("#fff3cd"))
#let todo(body) = callout("TODO.", body, rgb("#fdeaea"))

// ---------- Theorem Environments ----------
#let _env-title(name, kind, title: none) = strong[
  #name #context counter(figure.where(kind: kind)).display()#if title != none [ (#title)].
]

#let _env-box(name, kind, title: none, accent: rgb("#4c78a8"), fill: rgb("#f7fbff"), body) = block(
  fill: fill,
  inset: (x: 0.85em, y: 0.7em),
  radius: 4pt,
  stroke: (left: 1.8pt + accent),
  width: 100%,
  above: 0.65em,
  below: 0.65em,
)[
  #_env-title(name, kind, title: title)
  #v(0.35em)
  #body
]

// Theorem-like environments are custom figures. This keeps existing
// `#theorem[...]`-style calls while allowing normal Typst labels after the call:
// `#theorem[Body] <thm:name>` and references with `@thm:name`.
#let env(
  name,
  title: none,
  kind: none,
  accent: rgb("#4c78a8"),
  fill: rgb("#f7fbff"),
  body,
) = {
  let env-kind = if kind == none { name } else { kind }
  figure(
    _env-box(name, env-kind, title: title, accent: accent, fill: fill, body),
    kind: env-kind,
    supplement: name,
    numbering: "1",
    outlined: false,
  )
}
#let definition(title: none, body) = env(
  "Definition",
  title: title,
  kind: "definition",
  accent: rgb("#5b8c5a"),
  fill: rgb("#f7fbf5"),
  body,
)
#let theorem(title: none, body) = env(
  "Theorem",
  title: title,
  kind: "theorem",
  accent: rgb("#4c78a8"),
  fill: rgb("#f5f9ff"),
  body,
)
#let lemma(title: none, body) = env(
  "Lemma",
  title: title,
  kind: "theorem",
  accent: rgb("#4c78a8"),
  fill: rgb("#f5f9ff"),
  body,
)
#let proposition(title: none, body) = env(
  "Proposition",
  title: title,
  kind: "theorem",
  accent: rgb("#4c78a8"),
  fill: rgb("#f5f9ff"),
  body,
)
#let corollary(title: none, body) = env(
  "Corollary",
  title: title,
  kind: "theorem",
  accent: rgb("#4c78a8"),
  fill: rgb("#f5f9ff"),
  body,
)
#let example(title: none, body) = env(
  "Example",
  title: title,
  kind: "example",
  accent: rgb("#8a6fb0"),
  fill: rgb("#fbf8ff"),
  body,
)
#let remark(title: none, body) = env(
  "Remark",
  title: title,
  kind: "remark",
  accent: rgb("#777777"),
  fill: rgb("#fafafa"),
  body,
)
#let proof(title: none, qed: $square$, body) = block(
  fill: rgb("#fcfcfc"),
  inset: (x: 0.85em, y: 0.6em),
  radius: 3pt,
  stroke: (left: 1.2pt + rgb("#777777")),
  width: 100%,
  above: 0.45em,
  below: 0.65em,
)[
  #strong[Proof#if title != none [ (#title)].]
  #v(0.3em)
  #body#if qed != none [ #h(1fr) #qed]
]

// ---------- Formatting ----------
#let term(x) = emph(x)
#let key(x) = strong(x)
#let hr() = line(length: 100%)
#let space(amount: 1em) = v(amount)
