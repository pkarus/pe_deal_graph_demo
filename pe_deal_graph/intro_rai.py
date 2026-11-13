"""RAI introduction queries for the enriched test (not the original demo).

Reuse the base RAI Knows output, derive the small enrichment from its raw facts,
then use RAI distance and bounded dynamic programming to rank shortest routes.
Python only formats returned rows; it does not traverse the graph. Live execution
is deliberately opt-in and refuses a suspended reasoner. No deployment on import.
"""
from datetime import date
from pathlib import Path
import json
import math as pymath
import os

from relationalai.semantics import Model, String, Float, Integer, Date
from relationalai.semantics.reasoners.graph import Graph
from relationalai.semantics.std import aggregates as aggs, strings, floats, math, datetime as dt
from . import settings

AS_OF = date(2026, 10, 1)
SOURCE = settings.schema('CONNECTED_1M_INTRO_TEST')
BASE = settings.schema('CONNECTED_1M')


def configuration():
    from relationalai.config import create_config
    os.environ['RAI_CONFIG_FILE_PATH'] = str(Path(__file__).resolve().parents[1] / 'raiconfig.yaml')
    cfg = create_config()
    cfg.model.path = None
    cfg.oplog.enabled = False
    cfg.deployment = None
    cfg.execution.retries.enabled = False
    cfg.get_default_connection().role = settings.ADMIN_ROLE
    cfg.get_default_connection().warehouse = settings.WAREHOUSE
    return cfg


def _recency(value):
    return [((value >= date(2016, 10, 1),), 1.),
            ((value < date(2016, 10, 1), value >= date(2006, 10, 1)), .7),
            ((value < date(2006, 10, 1),), .4)]


class IntroductionModel:
    def __init__(self, config=None, min_strength=0., source_schema=SOURCE, base_schema=BASE):
        if isinstance(min_strength, bool) or not pymath.isfinite(min_strength) or not 0 <= min_strength <= 1:
            raise ValueError('min_strength must be finite and between 0 and 1')
        self.source, self.base = source_schema, base_schema
        self.model = m = Model('PE enriched introductions RAI', config=config or configuration())
        self.person = p = m.Concept('Person', identify_by={'id': String})
        p.name = m.Property(f'{p} has {String:name}')
        people = m.Table(self.base + '.PERSON')
        labels = m.Table(self.source + '.PERSON_LABEL')
        m.define(p.new(id=people.ID))
        m.where(people.ID == labels.ID).define(p.lookup(id=people.ID).name(labels.NAME))
        label = labels.ref()
        m.where(m.not_(label.ID == people.ID)).define(p.lookup(id=people.ID).name(people.NAME))
        self.team = m.Relationship(f'{p} is on our team')
        members = m.Table(self.source + '.TEAM_MEMBERS')
        m.define(self.team(p.lookup(id=members.PERSON_ID)))
        self.evidence = ev = m.Relationship(f'{p:a} connects to {p:b} with {Float:w} because {String:why}')
        # Only the baseline output is reused. ADDED_EVIDENCE and KNOWS_EDGES
        # (the old SQL rules) are not inputs to this model.
        base = m.Table(self.base + '.KNOWS')
        m.define(ev(p.lookup(id=base.P1), p.lookup(id=base.P2), base.STRENGTH, base.EVIDENCE))
        self.added_evidence = m.Relationship(f'{p:a} has added tie {Float:w} to {p:b} because {String:why}')
        self._enrichment()
        ea, eb, ew, et = p.ref(), p.ref(), Float.ref(), String.ref()
        m.where(self.added_evidence(ea, ew, eb, et)).define(ev(ea, eb, ew, et))
        self.tie = tie = m.Relationship(f'{p:a} has tie {Float:w} to {p:b}')
        self.reason = reason = m.Relationship(f'{p:a} has explanation {String:why} to {p:b}')
        a, b, w, why = p.ref(), p.ref(), Float.ref(), String.ref()
        maximum = aggs.max(w).per(a, b).where(ev(a, b, w, why))
        m.where(ev(a, b, w, why), w == maximum, w >= min_strength).define(tie(a, w, b), tie(b, w, a))
        # Keep all strongest evidence, not an arbitrary explanation from a weaker tie.
        m.where(ev(a, b, w, why), tie(a, w, b)).define(reason(a, why, b), reason(b, why, a))
        self.graph = g = Graph(m, directed=False, weighted=False, node_concept=p)
        m.where(tie(a, w, b), a.id < b.id).define(g.Edge.new(src=a, dst=b))
        self._queries = 0

    def _enrichment(self):
        m, p = self.model, self.person
        def ev(a, b, w, why):
            return self.added_evidence(a, w, b, why)
        role = m.Concept('Role', identify_by={'id': String})
        for name, kind in [('person_id', String), ('org_id', String), ('org_name', String),
                           ('start', Date), ('end', Date), ('effective_end', Date)]:
            setattr(role, name, m.Property(f'{role} has {kind:{name}}'))
        table = m.Table(self.source + '.ROLE_HISTORY')
        r = role.lookup(id=table.ROLE_ID)
        # Membership alone must not create a clique among the 100 employees.
        m.where(model_not_team := m.not_(strings.startswith(table.ROLE_ID, 'EXP_TEAM_'))).define(role.new(id=table.ROLE_ID))
        for name, column in [('person_id', table.PERSON_ID), ('org_id', table.ORG_ID),
                             ('org_name', table.ORG_NAME), ('start', table.START_DATE), ('end', table.END_DATE)]:
            m.where(model_not_team).define(getattr(r, name)(column))
        m.define(role.effective_end(role.end))
        m.where(m.not_(role.end)).define(role.effective_end(AS_OF))
        a, b = role.ref(), role.ref()
        # Choose overlap endpoints with separate rules (dates are not numeric min/max).
        overlap = m.Concept('TenureOverlap', identify_by={'a': role, 'b': role})
        overlap.start = m.Property(f'{overlap} starts {Date:start}')
        overlap.end = m.Property(f'{overlap} ends {Date:end}')
        o = overlap.new(a=a, b=b)
        common = (a.org_id == b.org_id, a.person_id < b.person_id)
        m.where(*common).define(o)
        m.where(*common, a.start >= b.start).define(o.start(a.start))
        m.where(*common, a.start < b.start).define(o.start(b.start))
        m.where(*common, a.effective_end <= b.effective_end).define(o.end(a.effective_end))
        m.where(*common, a.effective_end > b.effective_end).define(o.end(b.effective_end))
        o = overlap.ref()
        days = dt.date.period_days(o.start, o.end)
        for conditions, factor in _recency(o.end):
            m.where(days >= 365, *conditions).define(ev(
                p.lookup(id=o.a.person_id), p.lookup(id=o.b.person_id),
                factor * math.minimum(1., .4 + .15 * floats.float(days) / 365.25),
                strings.concat('K1 employment overlap at ', o.a.org_name, ': ', strings.string(o.start),
                               ' to ', strings.string(o.end), '; ', strings.string(days), ' days')))
        # The enrichment's deal facts already name both participants. Preserve
        # its current rule; do not invent additional CEO/CFO participation.
        deal = m.Table(self.source + '.DEAL_PARTY')
        d1, d2 = deal.ref(), deal.ref()
        for conditions, factor in _recency(d1.CLOSE_DATE):
            m.where(d1.TRANSACTION_ID == d2.TRANSACTION_ID, d1.LEAD_PERSON_ID < d2.LEAD_PERSON_ID,
                    *conditions).define(ev(p.lookup(id=d1.LEAD_PERSON_ID), p.lookup(id=d2.LEAD_PERSON_ID), .7 * factor,
                strings.concat('K2 transaction ', d1.TRANSACTION_ID, ' closed ', strings.string(d1.CLOSE_DATE),
                               '; ', d1.PARTY_ROLE, ' / ', d2.PARTY_ROLE)))
        crm = m.Table(self.source + '.CRM_INTERACTION')
        sender, contact = p.ref(), p.ref()
        c = crm.ref()
        valid = (sender.id == c.OUR_PERSON_ID, contact.id == c.COUNTERPARTY_PERSON_ID,
                 self.team(sender), sender != contact, c.SENTIMENT == 'positive',
                 c.INTERACTION_DATE >= date(2024, 10, 1), c.INTERACTION_DATE <= AS_OF)
        count = aggs.count(c.INTERACTION_ID).per(sender, contact).where(*valid)
        first = aggs.min(c.INTERACTION_DATE).per(sender, contact).where(*valid)
        last = aggs.max(c.INTERACTION_DATE).per(sender, contact).where(*valid)
        for lo, hi in [(sender, contact), (contact, sender)]:
            for condition, weight in [(count == 1, .6), (count == 2, .8), (count >= 3, 1.)]:
                m.where(*valid, lo.id < hi.id, condition).define(ev(lo, hi, weight,
                    strings.concat('K3 ', strings.string(count), ' positive CRM interactions: ',
                                   strings.string(first), ' to ', strings.string(last))))

    def route_query(self, target_id: str, source_id: str = '', max_hops: int = 12):
        """RAI computes distances and max-product shortest routes; one row/source.

        Only bounded witnesses are materialized, not every possible route. Equal
        products choose one deterministic witness, not a business tie-break.
        Longer reachable distances are reported even when the witness cap is hit.
        """
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError('target_id must be nonempty')
        if not isinstance(source_id, str):
            raise ValueError('source_id must be a string')
        if type(max_hops) is not int or not 0 <= max_hops <= 12:
            raise ValueError('max_hops must be an integer between 0 and 12')
        m, p = self.model, self.person
        self._queries += 1
        tag = self._queries
        target = m.Relationship(f'{p} is requested target {tag}')
        sources = m.Relationship(f'{p} is requested source {tag}')
        m.where(p.id == target_id).define(target(p))
        m.where(p.id == source_id if source_id else self.team(p)).define(sources(p))
        distance = self.graph.distance(from_=target)
        a, b, root, h = p.ref(), p.ref(), p.ref(), Integer.ref()
        previous = m.Relationship(f'{p} has score {Float:w} route {String:route} at layer 0 query {tag}')
        m.where(target(p)).define(previous(p, 1., p.id))
        all_routes = m.Relationship(f'{p} has requested score {Float:w} route {String:route} query {tag}')
        w, route = Float.ref(), String.ref()
        m.where(previous(a, w, route)).define(all_routes(a, w, route))
        for level in range(1, max_hops + 1):
            candidate = m.Relationship(f'{p} has candidate {Float:w} route {String:route} layer {level} query {tag}')
            link, tail, suffix = Float.ref(), Float.ref(), String.ref()
            m.where(distance(root, a, level), previous(b, tail, suffix), self.tie(a, link, b)).define(
                candidate(a, link * tail, strings.concat(a.id, '|', suffix)))
            current = m.Relationship(f'{p} has best {Float:w} route {String:route} layer {level} query {tag}')
            best = aggs.max(w).per(a).where(candidate(a, w, route))
            best_route = aggs.min(route).per(a, w).where(candidate(a, w, route))
            m.where(candidate(a, w, route), w == best, route == best_route).define(current(a, w, route))
            m.where(current(a, w, route)).define(all_routes(a, w, route))
            previous = current
        # Separate status rows ensure isolated/unreachable sources never vanish.
        result = m.Relationship(f'{p} has distance {Integer:h} score {Float:w} route {String:r} status {String:s} query {tag}')
        m.where(sources(a), distance(root, a, h), all_routes(a, w, route)).define(result(a, h, w, route, 'reachable'))
        m.where(sources(a), distance(root, a, h), h > max_hops).define(result(a, h, -1., '', 'beyond_route_limit'))
        m.where(sources(a), target(root), m.not_(distance(root, a, h))).define(result(a, -1, -1., '', 'unreachable'))
        status = String.ref()
        return m.where(result(a, h, w, route, status)).select(
            a.id.alias('source_id'), a.name.alias('source_name'), h.alias('hops'),
            w.alias('product_strength'), route.alias('route_ids'), status.alias('status'))

    def communities(self, levels=5, seed=7, pivots=2000, exact_up_to=200):
        """Use the same enriched graph; this is a separate, explicit calculation."""
        from .communities import community_connectors
        return community_connectors(self.model, self.person, self.graph, max_levels=levels,
                                    randomization_seed=seed, exact_pivots=1_000_000,
                                    num_pivots=pivots, exact_up_to=exact_up_to)

    def require_ready(self):
        """Read status only. Never resume, create or resize a reasoner."""
        cfg = self.model.config
        rows = cfg.get_session().sql('SELECT STATUS FROM RELATIONALAI.API.REASONERS WHERE NAME = ?',
                                    params=[cfg.reasoners.logic.name]).collect()
        if len(rows) != 1 or rows[0][0] != 'READY':
            raise RuntimeError('Existing reasoner is not READY; no engine changes attempted')

    def routes(self, target_id: str, source_id: str = '', max_hops: int = 12):
        """Execute only after READY check; return IDs and RAI-computed scores.

        Attribute/name resolution remains the existing test agent's search tool.
        This method accepts resolved stable IDs and fails explicitly for unknown IDs.
        """
        self.require_ready()
        p, m = self.person, self.model
        requested = [target_id] + ([source_id] if source_id else [])
        endpoints = m.where(p.id.in_(requested)).select(p.id.alias('id')).to_df()
        if set(requested) - set(endpoints['id']):
            raise ValueError('Unknown source or target ID')
        frame = self.route_query(target_id, source_id, max_hops).to_df()
        # Formatting only: the route IDs and products have already been computed
        # by RAI. Ask RAI for names and evidence for exactly those returned edges.
        route_ids = [r.split('|') if r else [] for r in frame['route_ids']]
        ids = sorted({node for route in route_ids for node in route})
        names_frame = m.where(p.id.in_(ids)).select(p.id.alias('id'), p.name.alias('name')).to_df() if ids else None
        names = dict(zip(names_frame['id'], names_frame['name'])) if ids else {}
        requested_edges = m.Relationship(f'{p:a} is a returned route edge to {p:b} query {self._queries}')
        pairs = {(a, b) for route in route_ids for a, b in zip(route, route[1:])}
        for a_id, b_id in sorted(pairs):
            m.define(requested_edges(p.lookup(id=a_id), p.lookup(id=b_id)))
        details = {}
        if pairs:
            a, b, weight, why = p.ref(), p.ref(), Float.ref(), String.ref()
            edges = m.where(requested_edges(a, b), self.tie(a, weight, b), self.reason(a, why, b)).select(
                a.id.alias('a'), b.id.alias('b'), weight.alias('strength'), why.alias('evidence')).to_df()
            for row in edges.to_dict('records'):
                key = (row['a'], row['b'])
                item = details.setdefault(key, dict(source_id=row['a'], target_id=row['b'],
                    strength=float(row['strength']), evidence=[]))
                item['evidence'].append(row['evidence'])
        for route in route_ids:
            if any(node not in names for node in route) or any(pair not in details for pair in zip(route, route[1:])):
                raise RuntimeError('RAI returned a route without complete names/evidence')
        frame['route_names'] = [json.dumps([names[n] for n in route]) for route in route_ids]
        frame['links'] = [json.dumps([details[pair] for pair in zip(route, route[1:])]) for route in route_ids]
        frame['hops'] = frame['hops'].astype(int)
        frame['product_strength'] = frame['product_strength'].astype(float)
        frame.loc[frame['hops'] == 0, 'status'] = 'self'
        # Missing distances are not zero; strength -1 is a status sentinel only.
        frame['reachable'] = frame['hops'] >= 0
        frame = frame.sort_values(['reachable', 'hops', 'product_strength', 'source_id'],
                                  ascending=[False, True, False, True]).reset_index(drop=True)
        return frame


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-id', required=True)
    parser.add_argument('--source-id', default='', help='Omit to compare all 100 team members')
    parser.add_argument('--min-strength', type=float, default=0.)
    parser.add_argument('--max-hops', type=int, default=12)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    query_model = IntroductionModel(min_strength=args.min_strength)
    if args.execute:
        result = query_model.routes(args.target_id, args.source_id, args.max_hops)
        print(result.to_json(orient='records', indent=2))
    else:
        query_model.route_query(args.target_id, args.source_id, args.max_hops).to_metamodel()
        print('PyRel query defined only. No live computation or agent changes.')
