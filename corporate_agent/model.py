"""Native RAI reachability plus strongest bounded introduction routes."""
from relationalai.semantics import Integer,Float,String
from relationalai.semantics.std import aggregates as aggs,strings
from .scoring import ScoredNetwork,SOURCE,CORPORATE,AS_OF,DEFAULT_PERSON,validate_person_id,normalize_strength


class IntroductionGraph(ScoredNetwork):
    def __init__(self,person_id,source_id='',min_strength=0.,config=None,source=SOURCE,**kwargs):
        super().__init__(person_id,source_id,min_strength=min_strength,config=config,source=source,**kwargs)
        self._routes()

    def _routes(self):
        m,p=self.model,self.person
        candidate=self.candidate=m.Relationship(f'{p:source} has candidate {Integer:hops} score {Float:strength} route {String:path} reason {String:why}')
        a,b,t=p.ref(),p.ref(),p.ref()
        w1,w2=Float.ref(),Float.ref();why1,why2=String.ref(),String.ref()
        m.where(self.sources(a),self.focus(t),a!=t,self.tie(a,w1,t),self.reason(a,why1,t)).define(
            candidate(a,1,w1,strings.concat(a.id,'|',t.id),strings.concat(a.name,' → ',t.name,': ',why1)))
        m.where(self.sources(a),self.focus(t),a!=t,a!=b,b!=t,self.tie(a,w1,b),self.tie(b,w2,t),
                self.reason(a,why1,b),self.reason(b,why2,t)).define(
            candidate(a,2,w1*w2,strings.concat(a.id,'|',b.id,'|',t.id),
                strings.concat(a.name,' → ',b.name,': ',why1,'; ',b.name,' → ',t.name,': ',why2)))
        h,w,path,why=Integer.ref(),Float.ref(),String.ref(),String.ref()
        conditions=candidate(a,h,w,path,why)
        maximum=aggs.max(w).per(a).where(conditions)
        fewest_at_score=aggs.min(h).per(a,w).where(conditions)
        witness=aggs.min(path).per(a,h,w).where(conditions)
        self.best_route=m.Relationship(f'{p:source} has strongest {Integer:hops} score {Float:strength} raw score {Float:raw_strength} route {String:path} reason {String:why}')
        m.where(conditions,w==maximum,h==fewest_at_score,path==witness).define(self.best_route(a,h,normalize_strength(w),w,path,why))
        fewest=aggs.min(h).per(a).where(conditions)
        at_hops=aggs.max(w).per(a,h).where(conditions)
        self.shortest_route=m.Relationship(f'{p:source} has shortest {Integer:hops} score {Float:strength} raw score {Float:raw_strength} route {String:path} reason {String:why}')
        m.where(conditions,h==fewest,w==at_hops,path==witness).define(self.shortest_route(a,h,normalize_strength(w),w,path,why))
