import type { GraphDTO, GraphEdge } from './client';
export type NetworkMetric={community_id:string;betweenness:number;degree:number;weighted_degree:number};
export type Career={role_id:string;company_id:string;company:string;title:string;start_date:string;end_date:string|null;tenure_years:number|string;office_id:string|null;city_id:string|null;work_mode:string};
export type Person={id:string;name:string;history:Career[];network:NetworkMetric|null;network_scope:string|null;as_of:string};
export type CorporateEdge=GraphEdge & {strength:number;raw_strength:number};
export type Period={start_date:string;end_date:string;days:number;recency_band:string;spatial_factor:number;decay_factor:number;weighted_days:number;supporting_employment:{company:string;office_a:string;office_b:string;spatial_basis:string}[]};
export type Breakdown={left_name:string;right_name:string;strength:number;raw_strength:number;left_career_years:number;right_career_years:number;career_mean_years:number;raw_years:number;effective_years:number;career_fraction:number;duration_component:number;time_score:number;employment_contribution:number;friendship_contribution:number;friendship_status:string;friendship_source:string;formula:string;scoring_version:string;as_of:string;periods:Period[];transaction_ids:string[]};
export type Neighborhood={center:Person;graph:Omit<GraphDTO,'edges'>&{edges:CorporateEdge[]};total_neighbors:number;shown_neighbors:number;cached:boolean;computed_at:string;computation_seconds:number;source:string;algorithm:string;scope:string;as_of:string;transaction_ids:string[]};
export type Network={metadata:{node_count:number;edge_count:number;community_count:number;nontrivial_community_count:number;isolated_people:number;scope:string;computed_at:string;betweenness_method:string;min_strength:number;min_raw_strength:number};communities:string[];shown_nodes:number;shown_edges:number;display_scope:string;graph:Omit<GraphDTO,'edges'>&{edges:CorporateEdge[]}};
export type SearchResult={id:string;name:string;title:string;company:string};
export async function corporateGet<T>(path:string):Promise<T>{
 const response=await fetch(`${process.env.NEXT_PUBLIC_API_URL??''}/api/corporate/${path}`);
 if(!response.ok){const body=await response.json().catch(()=>({detail:response.statusText}));throw new Error(typeof body.detail==='string'?body.detail:'The request could not be completed.');}
 return response.json();
}
