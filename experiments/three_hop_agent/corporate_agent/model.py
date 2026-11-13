"""Native RAI reachability plus strongest bounded introduction routes."""
from relationalai.semantics import Integer,Float,String
from relationalai.semantics.std import aggregates as aggs,strings,math,floats
from .scoring import ScoredNetwork,SOURCE,CORPORATE,AS_OF,DEFAULT_PERSON,EPOCH,decay_bands,validate_person_id,normalize_strength

ROUTING_VERSION='corporate-routes-v2-three-hops'


class IntroductionGraph(ScoredNetwork):
    def __init__(self,person_id,source_id='',min_strength=0.,config=None,source=SOURCE,**kwargs):
        kwargs.setdefault('max_hops',3)
        super().__init__(person_id,source_id,min_strength=min_strength,config=config,source=source,include_middle=False,with_evidence=False,**kwargs)
        if self.max_hops==3:self._add_competitive_bridges(person_id,source_id,min_strength,config,source,kwargs)
        self._routes()

    def _add_competitive_bridges(self,person_id,source_id,min_strength,config,source,kwargs):
        """Admissible native bound: a middle edge cannot exceed one.

        Keep every bridge that could match or beat the best <=2-edge score.
        Sources without a shorter path have bound zero, retaining all bridges.
        The complete anchor graph preserves distances 1/2; the latter sources
        retain every 3-edge path, so bounded shortest distance remains exact.
        """
        m,p=self.model,self.person
        a,b,c,t=p.ref(),p.ref(),p.ref(),p.ref()
        w1,w2,w3=Float.ref(),Float.ref(),Float.ref()
        baseline=m.Relationship(f'{p:source} has shorter candidate score {Float:score}')
        m.where(self.sources(a),self.focus(t),a!=t,self.tie(a,w1,t)).define(baseline(a,w1))
        m.where(self.sources(a),self.focus(t),a!=t,a!=b,b!=t,self.tie(a,w1,b),self.tie(b,w2,t)).define(baseline(a,w1*w2))
        best=aggs.max(w2).per(a).where(baseline(a,w2))|0.
        known=m.Relationship(f'{String:left} has already scored anchor edge to {String:right}')
        m.define(known(self.edge.left_id,self.edge.right_id),known(self.edge.right_id,self.edge.left_id))
        needed=self.bridge_pairs=m.Relationship(f'{String:left} needs middle scoring with {String:right}')
        rb,rc=self.role.ref(),self.role.ref()
        bound=(self.sources(a),self.focus(t),a!=t,a!=b,a!=c,b!=c,b!=t,c!=t,
               self.tie(a,w1,b),self.tie(c,w3,t),w1*w3+1e-12>=best,m.not_(known(b.id,c.id)),
               rb.person_id==b.id,rc.person_id==c.id,rb.org_id==rc.org_id,rb.org_id!='PE_FIRM_NORTHWIND',
               math.minimum(rb.end_day,rc.end_day)-math.maximum(rb.start_day,rc.start_day)>=365)
        potential=m.Relationship(f'{self.role:left} is a potentially competitive overlap with {self.role:right}')
        m.where(*bound,b.id<c.id).define(potential(rb,rc))
        m.where(*bound,c.id<b.id).define(potential(rc,rb))
        possible_pair=m.Relationship(f'{String:left} has potential middle overlap with {String:right}')
        m.where(potential(rb,rc)).define(possible_pair(rb.person_id,rc.person_id))
        # Summed raw overlap (including duplicates) is an admissible upper
        # bound on unioned, spatially/temporally weighted overlap. Apply the
        # unchanged monotone score formula to that bound before expensive
        # interval-union and decay scoring. This preserves all winning routes.
        l,r=p.ref(),p.ref()
        upper_days=aggs.sum(math.minimum(rb.end_day,rc.end_day)-math.maximum(rb.start_day,rc.start_day)).per(l,r).where(
            potential(rb,rc),rb.person_id==l.id,rc.person_id==r.id)
        spatial=m.Relationship(f'{self.role:left} has potential spatial factor {Float:factor} with {self.role:right}')
        m.where(potential(rb,rc)).define(spatial(rb,.25,rc))
        onsite=(potential(rb,rc),rb.work_mode=='ONSITE',rc.work_mode=='ONSITE')
        m.where(*onsite,rb.city_id!='',rb.city_id==rc.city_id).define(spatial(rb,.6,rc))
        m.where(*onsite,rb.office_id!='',rb.office_id==rc.office_id).define(spatial(rb,1.,rc))
        factor=Float.ref()
        max_spatial=aggs.max(factor).per(l,r).where(spatial(rb,factor,rc),rb.person_id==l.id,rc.person_id==r.id)
        last_end=aggs.max(math.minimum(rb.end_day,rc.end_day)).per(l,r).where(potential(rb,rc),rb.person_id==l.id,rc.person_id==r.id)
        recency=m.Relationship(f'{p:left} has upper decay factor {Float:factor} with {p:right}')
        for _,low,_,decay,_ in decay_bands(self.as_of):
            m.where(possible_pair(l.id,r.id),last_end>=(low-EPOCH).days).define(recency(l,decay,r))
        max_decay=aggs.max(factor).per(l,r).where(recency(l,factor,r))
        # Taking maxima across witnesses/periods can overestimate evidence,
        # never underestimate it; only the final shared scorer sets weights.
        upper_years=floats.float(upper_days)/365.25*max_spatial*max_decay
        mean=(l.career_years+r.career_years)/2.
        duration=math.minimum(upper_years/10.,1.)
        upper_score=.5*math.minimum(upper_years/mean,1.)+.5*duration*duration
        bound_score=m.Relationship(f'{p:left} has middle upper score {Float:score} to {p:right}')
        m.where(possible_pair(l.id,r.id),mean>0.).define(bound_score(l,upper_score,r),bound_score(r,upper_score,l))
        upper=Float.ref()
        competitive=(self.sources(a),self.focus(t),a!=t,a!=b,a!=c,b!=c,b!=t,c!=t,
                     self.tie(a,w1,b),self.tie(c,w3,t),bound_score(b,upper,c),w1*w3*upper+1e-12>=best)
        m.where(*competitive,b.id<c.id).define(needed(b.id,c.id))
        m.where(*competitive,c.id<b.id).define(needed(c.id,b.id))
        bridge=self.bridge_network=ScoredNetwork(person_id,source_id,mode='bridge',min_strength=min_strength,
            config=config,source=source,as_of=self.as_of,inputs=kwargs.get('inputs'),
            shared_model=m,prefix='Bridge',pair_scope=needed,with_evidence=False)
        all_tie=m.Relationship(f'{p:a} has bounded search affinity {Float:strength} to {p:b}')
        all_reason=m.Relationship(f'{p:a} has bounded search evidence {String:why} to {p:b}')
        why=String.ref()
        m.where(self.tie(b,w1,c)).define(all_tie(b,w1,c))
        m.where(self.reason(b,why,c)).define(all_reason(b,why,c))
        x,y=bridge.person.ref(),bridge.person.ref()
        left,right=p.lookup(id=x.id),p.lookup(id=y.id)
        m.where(bridge.tie(x,w1,y)).define(all_tie(left,w1,right))
        m.where(bridge.reason(x,why,y)).define(all_reason(left,why,right))
        m.where(bridge.tie(x,w1,y),x.id<y.id).define(self.graph.Edge.new(src=left,dst=right),
            self.affinity_graph.Edge.new(src=left,dst=right,weight=w1))
        self.tie,self.reason=all_tie,all_reason

    def _routes(self):
        m,p=self.model,self.person
        # Rank compact native node references and numbers. Never construct
        # long evidence strings for the potentially huge candidate relation.
        candidate=self.candidate=m.Relationship(f'{p:source} has candidate {Integer:hops} score {Float:strength} via {p:first} then {p:second}')
        a,b,c,t=p.ref(),p.ref(),p.ref(),p.ref()
        w1,w2,w3=Float.ref(),Float.ref(),Float.ref()
        m.where(self.sources(a),self.focus(t),a!=t,self.tie(a,w1,t)).define(candidate(a,1,w1,t,t))
        m.where(self.sources(a),self.focus(t),a!=t,a!=b,b!=t,self.tie(a,w1,b),self.tie(b,w2,t)).define(candidate(a,2,w1*w2,b,t))
        if self.max_hops==3:
            suffix=m.Relationship(f'{p:start} has two-edge suffix score {Float:score} via {p:middle}')
            m.where(self.focus(t),b!=t,b!=c,c!=t,self.tie(b,w2,c),self.tie(c,w3,t)).define(suffix(b,w2*w3,c))
            tail_score=Float.ref();mid=p.ref()
            best_tail=aggs.max(tail_score).per(b).where(suffix(b,tail_score,mid))
            # Share the best two-edge suffix across starting people. Retain
            # near ties, then rank the original left-associated raw products.
            # A suffix revisiting the source cannot beat that source's direct
            # edge (all weights <=1); excluding it cannot hide a winning path.
            m.where(self.sources(a),self.focus(t),a!=t,a!=b,a!=c,b!=c,b!=t,c!=t,
                    self.tie(a,w1,b),suffix(b,tail_score,c),tail_score+1e-12>=best_tail,
                    self.tie(b,w2,c),self.tie(c,w3,t)).define(candidate(a,3,w1*w2*w3,b,c))
        h,w=Integer.ref(),Float.ref()
        conditions=candidate(a,h,w,b,c)
        maximum=aggs.max(w).per(a).where(conditions)
        fewest_at_score=aggs.min(h).per(a,w).where(conditions)
        fewest=aggs.min(h).per(a).where(conditions)
        at_hops=aggs.max(w).per(a,h).where(conditions)
        # Within fixed source/target and hop count, intermediate IDs are the
        # lexicographic path tie-break, without materializing path strings.
        first=aggs.min(b.id).per(a,h,w).where(conditions)
        second=aggs.min(c.id).per(a,h,w,b).where(conditions)
        for attr,rank in [('best_route',(w==maximum,h==fewest_at_score)),
                          ('shortest_route',(h==fewest,w==at_hops))]:
            selected=m.Relationship(f'{p:source} has {attr} selection {Integer:hops} score {Float:strength} via {p:first} then {p:second}')
            m.where(conditions,*rank,b.id==first,c.id==second).define(selected(a,h,w,b,c))
            result=m.Relationship(f'{p:source} has {attr} {Integer:hops} score {Float:strength} raw score {Float:raw_strength} route {String:path} reason {String:why}')
            setattr(self,attr,result)
            note='; qualifying shared-employment evidence and calculations are supplied for each selected connection.'
            m.where(selected(a,1,w,t,t),self.focus(t)).define(result(a,1,normalize_strength(w),w,
                strings.concat(a.id,'|',t.id),strings.concat(a.name,' → ',t.name,note)))
            m.where(selected(a,2,w,b,t),self.focus(t)).define(result(a,2,normalize_strength(w),w,
                strings.concat(a.id,'|',b.id,'|',t.id),strings.concat(a.name,' → ',b.name,' → ',t.name,note)))
            m.where(selected(a,3,w,b,c),self.focus(t)).define(result(a,3,normalize_strength(w),w,
                strings.concat(a.id,'|',b.id,'|',c.id,'|',t.id),strings.concat(a.name,' → ',b.name,' → ',c.name,' → ',t.name,note)))
