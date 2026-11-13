"""Prove the bounded suffix reduction against exhaustive simple-path enumeration."""
import itertools,random


def test_suffix_reduction_preserves_best_simple_route_and_ties():
    rng=random.Random(731)
    for _ in range(100):
        nodes=list(range(7));target=6;edges={}
        for a,b in itertools.combinations(nodes,2):
            if rng.random()<.55:edges[a,b]=edges[b,a]=rng.choice([.05,.1,.25,.5,.8,1.])
        for source in nodes[:-1]:
            all_routes=[]
            for hops in [1,2,3]:
                for middle in itertools.permutations([n for n in nodes if n not in [source,target]],hops-1):
                    path=(source,*middle,target);score=1.
                    for a,b in zip(path,path[1:]):score*=edges.get((a,b),0.)
                    if score:all_routes.append((score,hops,path))
            reduced=[]
            for score,hops,path in all_routes:
                if hops<3:reduced.append((score,hops,path));continue
                b,c=path[1:3]
                tails=[edges.get((b,x),0.)*edges.get((x,target),0.) for x in nodes if x not in [b,target]]
                if edges[b,c]*edges[c,target]+1e-12>=max(tails,default=0.):reduced.append((score,hops,path))
            rank=lambda r:(-r[0],r[1],r[2])
            assert sorted(all_routes,key=rank)[:1]==sorted(reduced,key=rank)[:1]
