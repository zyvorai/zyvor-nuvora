"""BM25 + hashed lexical vectors. Optional real embeddings via provider adapters."""
import collections
import hashlib
import math
import re


def tokens(text):
    return re.findall(r'[\w]+',text.lower())


def chunks(text, size=1000, overlap=150):
    if not 100<=size<=10000 or not 0<=overlap<size:
        raise ValueError('Invalid chunk configuration')
    return [{'index':i,'text':text[start:start+size],'start':start,'end':min(start+size,len(text))} for i,start in enumerate(range(0,len(text),size-overlap))]


def vector(text, dim=256):
    out=[0.0]*dim
    for term in tokens(text):
        digest=hashlib.sha256(term.encode()).digest()
        out[int.from_bytes(digest[:2],'big')%dim]+=1 if digest[2]%2 else -1
    norm=math.sqrt(sum(v*v for v in out)) or 1
    return [v/norm for v in out]


def cosine(a,b):
    if len(a)!=len(b):
        raise ValueError('Embedding dimensions changed; rebuild the knowledge base')
    na=math.sqrt(sum(x*x for x in a)) or 1
    nb=math.sqrt(sum(x*x for x in b)) or 1
    return sum(x*y for x,y in zip(a,b))/(na*nb)


def search(query, candidates, top_k=5, query_vector=None):
    if not candidates:
        return []
    docs=[collections.Counter(tokens(c['text'])) for c in candidates]
    lengths=[sum(d.values()) for d in docs]
    avg=sum(lengths)/len(lengths) or 1
    terms=set(tokens(query))
    df={t:sum(t in d for d in docs) for t in terms}
    lexical=[]
    for d,length in zip(docs,lengths):
        lexical.append(sum(math.log(1+(len(docs)-df[t]+.5)/(df[t]+.5))*d[t]*2.2/(d[t]+1.2*(.25+.75*length/avg)) for t in terms if d[t]))
    qv=query_vector or vector(query)
    semantic=[cosine(qv,c.get('embedding') or vector(c['text'])) for c in candidates]
    # Reciprocal rank fusion; never emit an unrelated zero-overlap lexical fallback.
    rank_a={i:r+1 for r,i in enumerate(sorted(range(len(candidates)),key=lambda i:lexical[i],reverse=True))}
    rank_b={i:r+1 for r,i in enumerate(sorted(range(len(candidates)),key=lambda i:semantic[i],reverse=True))}
    result=[]
    for i,c in enumerate(candidates):
        if (query_vector is None and lexical[i]<=0) or (query_vector is not None and lexical[i]<=0 and semantic[i]<=.2):
            continue
        result.append({**c,'score':1/(60+rank_a[i])+1/(60+rank_b[i]),'lexical_score':lexical[i],'vector_score':semantic[i]})
    return sorted(result,key=lambda x:x['score'],reverse=True)[:top_k]
