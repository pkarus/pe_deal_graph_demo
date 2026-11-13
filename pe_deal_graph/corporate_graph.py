"""On-demand native RAI neighborhoods using the agent's shared affinity rules."""
from relationalai.semantics import Integer,Float
from relationalai.semantics.std import aggregates as aggs
from corporate_agent.scoring import ScoredNetwork,SOURCE,CORPORATE,AS_OF,VERSION,DEFAULT_PERSON,validate_person_id
from .intro_rai import configuration

class CorporateNeighborhood(ScoredNetwork):
    def __init__(self,person_id,min_strength=0.,config=None,source=SOURCE,as_of=AS_OF):
        super().__init__(person_id,mode='neighborhood',min_strength=min_strength,
                         config=config or configuration(),source=source,as_of=as_of)
        self.distance=self.graph.distance(from_=self.focus)

    def query(self):
        m,p,e=self.model,self.person,self.edge
        center,neighbor,count_node=p.ref(),p.ref(),p.ref()
        h,count_h=Integer.ref(),Integer.ref();w=Float.ref()
        total=aggs.count(count_node).per(center).where(self.distance(center,count_node,count_h),count_h==1)
        # Canonical edge identity; the symmetric tie binds either endpoint.
        match=m.Relationship(f'{p:neighbor} has displayed connection {e:edge}')
        m.where(e.left.id==self.person_id).define(match(e.right,e))
        m.where(e.right.id==self.person_id).define(match(e.left,e))
        return m.where(self.distance(center,neighbor,h),h==1,match(neighbor,e),self.tie(center,w,neighbor)).select(
          center.id.alias('source_id'),neighbor.id.alias('person_id'),neighbor.name.alias('name'),
          h.alias('distance'),e.strength.alias('strength'),w.alias('raw_strength'),e.evidence.alias('evidence'),
          e.employment_contribution.alias('employment_contribution'),e.friendship_contribution.alias('friendship_contribution'),
          e.raw_years.alias('raw_years'),e.effective_years.alias('effective_years'),total.alias('total_neighbors'))

    def run(self,request_id=None):return self.query().meta(explorer_request_id=request_id or self.execution_id).to_df()
