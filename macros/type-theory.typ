// Type theory and logic notation.

#let Type = math.op("Type")
#let Prop = math.op("Prop")
#let Judg = math.op("J")

#let hastype(ctx, term, ty) = $#ctx tack.r #term : #ty$
#let defeq(x, y) = $#x equiv #y$
#let subst(term, var, val) = $#term [#val / #var]$
#let lam(var, body) = $lambda #var . #body$
#let Pi(var, ty, body) = $Pi (#var : #ty) . #body$
#let Sigma(var, ty, body) = $Sigma (#var : #ty) . #body$
