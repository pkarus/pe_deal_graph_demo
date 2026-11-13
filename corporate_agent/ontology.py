"""Business concepts for corporate introductions; scoring lives in scoring.py."""
from relationalai.semantics import String, Date, Float, Integer


def properties(model, concept, fields):
    for name, kind in fields:
        setattr(concept, name, model.Property(f'{concept} has {kind:{name}}'))


class CorporateOntology:
    """People and jobs, plus the connections and introduction routes they support."""

    def __init__(self, model):
        self.person = person = model.Concept('Person', identify_by={'id': String})
        properties(model, person, [('name', String), ('career_years', Float)])
        self.company = company = model.Concept('Company', identify_by={'id': String})
        properties(model, company, [('name', String)])
        self.employment = employment = model.Concept('Employment', identify_by={'id': String})
        employment.person = model.Property(f'{employment} is held by {person:person}')
        employment.company = model.Property(f'{employment} is at {company:company}')
        properties(model, employment,
                   [(n, String) for n in ['person_id', 'org_id', 'title', 'office_id', 'city_id', 'work_mode']]
                   + [(n, Date) for n in ['start_date', 'end_date']]
                   + [(n, Integer) for n in ['start_day', 'end_day', 'career_days']])
        person.employment = model.Relationship(f'{person} has employment {employment:employment}')
        company.employment = model.Relationship(f'{company} has employment {employment:employment}')
        self.our_team_member = model.Concept('OurTeamMember', extends=[person])
        self.connection = connection = model.Concept('Connection', identify_by={'left_id': String, 'right_id': String})
        properties(model, connection, [(n, Float) for n in [
            'raw_years', 'effective_years', 'career_fraction', 'duration_component',
            'time_score', 'friendship_score', 'employment_contribution', 'friendship_contribution',
            'strength', 'raw_strength', 'career_mean_years']]
            + [('friendship_status', String), ('friendship_source', String), ('evidence', String),
               ('left', person), ('right', person)])
        person.connection = model.Relationship(f'{person} has connection {connection:connection}')
        # A path is an ordered sequence of person IDs within this request/as-of model.
        self.introduction_route = route = model.Concept('IntroductionRoute', identify_by={'path': String})
        properties(model, route, [('source', person), ('target', person), ('hops', Integer),
                                 ('raw_strength', Float), ('strength', Float), ('reason', String)])
        route.via = model.Relationship(f'{route} goes via {person:via}')

    def connect(self, model, team):
        """Resolve typed links and classify existing people without duplicating identity."""
        person, company, employment = self.person, self.company, self.employment
        model.define(person.new(id=employment.person_id), company.new(id=employment.org_id))
        model.define(employment.person(person.lookup(id=employment.person_id)),
                     employment.company(company.lookup(id=employment.org_id)))
        model.where(employment.person(person)).define(person.employment(employment))
        model.where(employment.company(company)).define(company.employment(employment))
        model.where(person.id == team.PERSON_ID).define(self.our_team_member(person))
