// Stochastic-process notation.

#let Filtration = math.op("F")
#let Mart = math.op("Mart")
#let adapted = math.op("adapted")
#let predictable = math.op("predictable")
#let stopping = math.op("stopping")

#let FF(t) = $cal(F)_#t$
#let process(x, t) = $#x_#t$
#let stopped(x, tau, t) = $#x_(#t sect #tau)$
