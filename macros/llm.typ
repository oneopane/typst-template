// Transformer and LLM notation.

#let Attn = math.op("Attn")
#let MHA = math.op("MHA")
#let FFN = math.op("FFN")
#let LayerNorm = math.op("LayerNorm")
#let RMSNorm = math.op("RMSNorm")
#let RoPE = math.op("RoPE")
#let logits = math.op("logits")
#let tok = math.op("tok")

#let qkv(q, k, v) = $#q, #k, #v$
#let seq(x, first: 1, last: $n$) = $#x_(#first:#last)$
#let prefix(x, t) = $#x_(< #t)$
#let causal-attn(q, k, v, d) = $softmax(#q #k^top / sqrt(#d)) #v$
