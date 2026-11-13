"""Shared RAI-only affinity rules for the corporate agent and local explorer.

Ten business rules: eligibility, union career duration, spatial evidence,
five period-specific decay bands, and the original employment score at full weight.
No Python/SQL computation of production scores or graph structure.
"""
from datetime import date
import math as pymath
import re
import uuid
from relationalai.semantics import Model,String,Date,Float,Integer
from relationalai.semantics.reasoners.graph import Graph
from relationalai.semantics.std import aggregates as aggs,datetime as dt,floats,math,strings

VERSION='corporate-affinity-v5'
RAW_SCORING_VERSION='corporate-affinity-v4'
NORMALIZATION='fourth-root-v1'
SOURCE='ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_AGENT'
CORPORATE='ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_1M_SRC'
AS_OF=date(2026,10,1)
EPOCH=date(1900,1,1)
DEFAULT_PERSON='CORP_P000002008'


def normalize_strength(value):
    """Native RAI expression: fixed monotone scale, preserving products/ranks."""
    return math.sqrt(math.sqrt(value))


def validate_person_id(value):
    if not re.fullmatch(r'(?:CORP_P\d{9}|PE_P\d{4})',value):raise ValueError('Expected a corporate or PE person ID')
    return value


def validate_as_of(value):
    value=date.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(value,date) or not date(1940,1,1)<=value<=AS_OF:raise ValueError('as_of must be between 1940-01-01 and 2026-10-01')
    return value


def decay_bands(as_of):
    def ago(years):
        try:return as_of.replace(year=as_of.year-years)
        except ValueError:return as_of.replace(year=as_of.year-years,day=28)
    return [(0,ago(2),as_of,1.0,'0–2 years'),(1,ago(5),ago(2),.8,'2–5 years'),
            (2,ago(10),ago(5),.5,'5–10 years'),(3,ago(15),ago(10),.25,'10–15 years'),
            (4,EPOCH,ago(15),.1,'15+ years')]


def properties(model,concept,fields):
    for name,kind in fields:
        setattr(concept,name,model.Property(f'{concept} has {kind:{name}}'))


class ScoredNetwork:
    def __init__(self,person_id=DEFAULT_PERSON,source_id='',*,mode='introductions',min_strength=0.,
                 as_of=AS_OF,config=None,source=SOURCE,inputs=None):
        if mode not in ['introductions','neighborhood','cohort','pair']:raise ValueError('Invalid graph scope')
        validate_person_id(person_id)
        if source_id:validate_person_id(source_id)
        if not pymath.isfinite(min_strength) or not 0<=min_strength<=1:raise ValueError('Invalid minimum strength')
        self.as_of=as_of=validate_as_of(as_of);self.person_id=person_id;self.mode=mode
        self.execution_id=uuid.uuid4().hex
        self.model=m=Model('corporate_affinity_v5_'+self.execution_id,config=config)
        # inputs is used only by native-engine fixtures; production uses Snowflake base tables.
        def table(name,fqn):
            value=inputs[name] if inputs is not None else fqn
            return m.Table(value) if isinstance(value,str) else m.data(value)
        work=table('work',source+'.WORKPLACE_V2')
        team=table('team',source+'.TEAM_MEMBER')
        company=table('company',CORPORATE+'.COMPANY')
        anchors=self.anchors=m.Relationship(f'{String:id} is in the requested scope')
        if mode=='cohort':
            cohort=table('cohort',source+'.LEADERSHIP_COHORT_V2')
            m.define(anchors(cohort.PERSON_ID))
        else:
            m.define(anchors(person_id))
            if mode in ['introductions','pair']:
                if source_id:m.define(anchors(source_id))
                else:m.define(anchors(team.PERSON_ID))

        # Scope people before loading career roles, while retaining each
        # candidate's COMPLETE career for the normalization denominator.
        eligible=m.Relationship(f'{String:id} is a relevant career person')
        anchor_id=String.ref()
        m.where(anchors(anchor_id)).define(eligible(anchor_id))
        if mode not in ['cohort','pair']:
            aw=work.ref();bw=work.ref()
            # Every intermediate in a <=2-hop introduction is adjacent to
            # the target. A superset of its employment neighbors
            # plus all requested sources therefore preserves every such path.
            # Do not expand the careers of all 100 PE employees' neighbors.
            pivot=m.Relationship(f'{String:id} is a neighborhood expansion pivot')
            m.define(pivot(person_id))
            m.where(pivot(aw.PERSON_ID),aw.ORG_ID==bw.ORG_ID,aw.ORG_ID!='PE_FIRM_NORTHWIND').define(eligible(bw.PERSON_ID))
        role_scope=(eligible(work.PERSON_ID),work.START_DATE<as_of)
        role=self.role=m.Concept('CareerRole',identify_by={'id':String})
        properties(m,role,[(n,String) for n in ['person_id','org_id','office_id','city_id','work_mode']]+
          [(n,Integer) for n in ['start_day','end_day','career_days']]+[('recorded_end',Date)])
        r=role.new(id=work.ROLE_ID)
        m.where(*role_scope).define(r)
        # Never reuse the .new constructor for nullable property bindings:
        # constructor assignments make every supplied field required.
        r=role.lookup(id=work.ROLE_ID)
        for name,col in [('person_id',work.PERSON_ID),('org_id',work.ORG_ID),('office_id',work.OFFICE_ID),
                         ('city_id',work.CITY_ID),('work_mode',work.WORK_MODE)]:
            m.where(*role_scope).define(getattr(r,name)(col))
        m.where(*role_scope).define(r.start_day(dt.date.period_days(EPOCH,work.START_DATE)))
        m.where(*role_scope,work.END_DATE<=as_of).define(r.end_day(dt.date.period_days(EPOCH,work.END_DATE)))
        m.where(*role_scope,work.END_DATE>as_of).define(r.end_day((as_of-EPOCH).days))
        m.where(*role_scope).define(r.recorded_end(work.END_DATE))
        m.where(m.not_(role.recorded_end)).define(role.end_day((as_of-EPOCH).days))
        # Union-of-intervals career length, including concurrent records exactly once.
        a,b=role.ref(),role.ref()
        before=m.Relationship(f'{role:r} has prior ordered role {role:previous}')
        m.where(a.person_id==b.person_id,b.start_day<a.start_day).define(before(a,b))
        m.where(a.person_id==b.person_id,b.start_day==a.start_day,b.id<a.id).define(before(a,b))
        previous_end=aggs.max(b.end_day).per(a).where(before(a,b))|a.start_day
        m.define(a.career_days(math.maximum(0,a.end_day-math.maximum(a.start_day,previous_end))))

        edge=self.edge=m.Concept('ScoredConnection',identify_by={'left_id':String,'right_id':String})
        person=self.person=m.Concept('Person',identify_by={'id':String})
        properties(m,person,[('name',String),('career_years',Float)])
        properties(m,edge,[(n,Float) for n in ['raw_years','effective_years','career_fraction','duration_component',
          'time_score','friendship_score','employment_contribution','friendship_contribution','strength','raw_strength','career_mean_years']]+
          [('friendship_status',String),('friendship_source',String),('evidence',String),('left',person),('right',person)])
        overlap=self.overlap=m.Concept('SharedEmployment',identify_by={'role_a':role,'role_b':role})
        properties(m,overlap,[('edge',edge),('start_day',Integer),('end_day',Integer),('days',Integer),
          ('spatial_factor',Float),('spatial_basis',String),('company',String),('evidence',String)])
        oa,ob=role.ref(),role.ref()
        start=math.maximum(oa.start_day,ob.start_day);end=math.minimum(oa.end_day,ob.end_day)
        common=(oa.person_id<ob.person_id,oa.org_id==ob.org_id,oa.org_id!='PE_FIRM_NORTHWIND',end-start>=365)
        o=overlap.new(role_a=oa,role_b=ob)
        if mode in ['cohort','pair']:m.where(*common,anchors(oa.person_id),anchors(ob.person_id)).define(o)
        else:
            m.where(*common,anchors(oa.person_id)).define(o)
            m.where(*common,anchors(ob.person_id)).define(o)
        o=overlap.ref()
        m.define(edge.new(left_id=o.role_a.person_id,right_id=o.role_b.person_id))
        m.define(o.edge(edge.lookup(left_id=o.role_a.person_id,right_id=o.role_b.person_id)),
          o.start_day(math.maximum(o.role_a.start_day,o.role_b.start_day)),
          o.end_day(math.minimum(o.role_a.end_day,o.role_b.end_day)))
        m.define(o.days(o.end_day-o.start_day))
        m.where(company.COMPANY_ID==o.role_a.org_id).define(o.company(company.NAME))
        onsite=(o.role_a.work_mode=='ONSITE',o.role_b.work_mode=='ONSITE')
        same_office=m.Relationship(f'{overlap} has matching known onsite offices')
        same_city=m.Relationship(f'{overlap} has matching known onsite cities')
        m.where(*onsite,o.role_a.office_id!='',o.role_a.office_id==o.role_b.office_id).define(same_office(o))
        m.where(*onsite,o.role_a.city_id!='',o.role_a.city_id==o.role_b.city_id).define(same_city(o))
        m.where(same_office(o)).define(o.spatial_factor(1.),o.spatial_basis('Same office'))
        m.where(m.not_(same_office(o)),same_city(o)).define(
          o.spatial_factor(.6),o.spatial_basis('Same synthetic city; no matching office evidence'))
        m.where(m.not_(same_office(o)),m.not_(same_city(o))).define(
          o.spatial_factor(.25),o.spatial_basis('Different, remote or unknown locations; company-only evidence'))
        m.define(o.evidence(strings.concat(o.company,': ',strings.string(dt.date.fromordinal(o.start_day+EPOCH.toordinal())),
          ' to ',strings.string(dt.date.fromordinal(o.end_day+EPOCH.toordinal())),
          ' (',strings.string(o.days),' days; ',o.spatial_basis,')')))

        # Preserve friendship facts for later; they neither create edges nor
        # affect scores. Compatibility fields explicitly identify this policy.
        m.define(edge.friendship_score(0.),edge.friendship_status('Deferred; not used in scoring'),edge.friendship_source('Not used'))
        m.define(person.new(id=edge.left_id),person.new(id=edge.right_id))
        m.where(anchors(anchor_id)).define(person.new(id=anchor_id))
        m.define(edge.left(person.lookup(id=edge.left_id)),edge.right(person.lookup(id=edge.right_id)))
        for name,fqn in [('people',CORPORATE+'.PERSON'),('team',source+'.TEAM_MEMBER')]:
            data=table(name,fqn)
            m.define(person.lookup(id=data.PERSON_ID).name(data.FULL_NAME))
        pr=person.ref();rr=role.ref()
        career_days=aggs.sum(rr.career_days).per(pr).where(rr.person_id==pr.id)|0
        m.define(pr.career_years(floats.float(career_days)/365.25))
        m.define(edge.career_mean_years((edge.left.career_years+edge.right.career_years)/2.))

        # Union shared intervals before summing, taking the strongest spatial
        # evidence where concurrent assignments cover the same days.
        boundary=m.Relationship(f'{edge:e} has employment boundary {Integer:day}')
        m.define(boundary(o.edge,o.start_day),boundary(o.edge,o.end_day))
        er=edge.ref();begin,nxt=Integer.ref(),Integer.ref()
        finish=aggs.min(nxt).per(er,begin).where(boundary(er,nxt),nxt>begin)
        segment=self.segment=m.Concept('SharedSegment',identify_by={'edge':edge,'start_day':Integer})
        properties(m,segment,[('end_day',Integer),('days',Integer),('spatial_factor',Float)])
        seg=segment.new(edge=er,start_day=begin)
        coverage=(boundary(er,begin),finish>begin,o.edge==er,o.start_day<=begin,o.end_day>=finish)
        m.where(*coverage).define(seg,seg.end_day(finish))
        s=segment.ref()
        m.define(s.days(s.end_day-s.start_day))
        spatial=aggs.max(o.spatial_factor).per(s).where(o.edge==s.edge,o.start_day<=s.start_day,o.end_day>=s.end_day)
        m.define(s.spatial_factor(spatial))
        slice_=self.slice=m.Concept('DecaySlice',identify_by={'segment':segment,'bucket':Integer})
        properties(m,slice_,[('start_day',Integer),('end_day',Integer),('days',Integer),('decay_factor',Float),
          ('weighted_days',Float),('bucket_label',String)])
        for bucket,low,high,factor,label in decay_bands(as_of):
            lo=math.maximum(s.start_day,(low-EPOCH).days);hi=math.minimum(s.end_day,(high-EPOCH).days)
            part=slice_.new(segment=s,bucket=bucket)
            m.where(hi>lo).define(part,part.start_day(lo),part.end_day(hi),part.days(hi-lo),
              part.decay_factor(factor),part.bucket_label(label),
              part.weighted_days(floats.float(hi-lo)*factor*s.spatial_factor))
        part=slice_.ref()
        raw=aggs.sum(s.days).per(er).where(s.edge==er)|0
        effective=aggs.sum(part.weighted_days).per(er).where(part.segment.edge==er)|0.
        m.define(er.raw_years(floats.float(raw)/365.25),er.effective_years(effective/365.25))
        m.where(er.career_mean_years>0.).define(er.career_fraction(math.minimum(1.,er.effective_years/er.career_mean_years)))
        m.where(er.career_mean_years==0.).define(er.career_fraction(0.))
        duration=math.minimum(er.effective_years/10.,1.)
        m.define(er.duration_component(duration*duration))
        m.define(er.time_score(.5*er.career_fraction+.5*er.duration_component))
        m.define(er.employment_contribution(er.time_score),er.friendship_contribution(0.))
        m.define(er.raw_strength(math.minimum(1.,er.employment_contribution+er.friendship_contribution)))
        m.define(er.strength(normalize_strength(er.raw_strength)))
        # Full contributions are returned by period_query. The text field names
        # one representative employment; it never claims to enumerate all jobs.
        employers=aggs.min(o.evidence).per(er).where(o.edge==er)|'No qualifying employment overlap'
        m.define(er.evidence(strings.concat('Representative employment: ',employers,
          '; total shared years=',strings.string(er.raw_years),'; effective shared years=',strings.string(er.effective_years),'; ',er.friendship_status,
          '; employment contribution=',strings.string(er.employment_contribution),
          ', friendship contribution=',strings.string(er.friendship_contribution),', raw strength=',strings.string(er.raw_strength),'; normalized strength=',strings.string(er.strength))))

        self.tie=m.Relationship(f'{person:a} has affinity {Float:strength} to {person:b}')
        self.reason=m.Relationship(f'{person:a} has evidence {String:reason} to {person:b}')
        keep=(edge.strength>0.,edge.strength>=min_strength)
        m.where(*keep).define(self.tie(edge.left,edge.raw_strength,edge.right),self.tie(edge.right,edge.raw_strength,edge.left),
          self.reason(edge.left,edge.evidence,edge.right),self.reason(edge.right,edge.evidence,edge.left))
        self.graph=Graph(m,directed=False,weighted=False,node_concept=person)
        self.affinity_graph=Graph(m,directed=False,weighted=True,node_concept=person)
        m.where(*keep).define(self.graph.Edge.new(src=edge.left,dst=edge.right),
          self.affinity_graph.Edge.new(src=edge.left,dst=edge.right,weight=edge.raw_strength))
        self.focus=m.Relationship(f'{person} is the requested target')
        m.where(person.id==person_id).define(self.focus(person))
        self.sources=m.Relationship(f'{person} is a requested source')
        if source_id:m.where(person.id==source_id).define(self.sources(person))
        else:m.define(self.sources(person.lookup(id=team.PERSON_ID)))

    def edge_query(self,person_ids=None,min_strength=0.):
        e=self.edge;m=self.model
        fields=['raw_years','effective_years','career_mean_years','career_fraction','duration_component',
          'time_score','friendship_score','employment_contribution','friendship_contribution','strength','raw_strength',
          'friendship_status','friendship_source','evidence']
        conditions=[e.strength>0.,e.strength>=min_strength]
        if person_ids is not None:conditions += [e.left_id.in_(person_ids),e.right_id.in_(person_ids)]
        return m.where(*conditions).select(e.left_id.alias('left_id'),e.right_id.alias('right_id'),
          e.left.name.alias('left_name'),e.right.name.alias('right_name'),
          e.left.career_years.alias('left_career_years'),e.right.career_years.alias('right_career_years'),
          *[getattr(e,k).alias(k) for k in fields])

    def period_query(self,person_ids=None):
        part=self.slice;o=self.overlap;m=self.model;s=part.segment;e=s.edge
        conditions=[o.edge==e,o.start_day<=s.start_day,o.end_day>=s.end_day]
        if person_ids is not None:conditions += [e.left_id.in_(person_ids),e.right_id.in_(person_ids)]
        return m.where(*conditions).select(e.left_id.alias('left_id'),e.right_id.alias('right_id'),
          o.role_a.id.alias('role_a'),o.role_b.id.alias('role_b'),o.company.alias('company'),
          (o.role_a.office_id|'Unknown/remote').alias('office_a'),(o.role_b.office_id|'Unknown/remote').alias('office_b'),
          (o.role_a.city_id|'Unknown/remote').alias('city_a'),(o.role_b.city_id|'Unknown/remote').alias('city_b'),
          o.spatial_basis.alias('spatial_basis'),o.spatial_factor.alias('evidence_spatial_factor'),
          dt.date.fromordinal(part.start_day+EPOCH.toordinal()).alias('start_date'),
          dt.date.fromordinal(part.end_day+EPOCH.toordinal()).alias('end_date'),
          part.days.alias('days'),part.bucket.alias('bucket'),part.bucket_label.alias('recency_band'),
          part.decay_factor.alias('decay_factor'),s.spatial_factor.alias('spatial_factor'),
          part.weighted_days.alias('weighted_days'))
