"""Read-only diagnostics for a pinned COLMAP graph; never filters observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from scripts.pilot.atomic_json import write_json

# COLMAP 4.2.1 TwoViewGeometry::ConfigurationType.
CONFIGS={0:'UNDEFINED',1:'DEGENERATE',2:'CALIBRATED',3:'UNCALIBRATED',4:'PLANAR',
         5:'PANORAMIC',6:'PLANAR_OR_PANORAMIC',7:'WATERMARK',8:'MULTIPLE'}
PAIR_BASE=2147483647


def audit(prepared):
    import numpy as np

    prepared=Path(prepared).resolve(strict=True)
    database=prepared/'database.db';index=prepared/'reconstruction-input.json'
    if (database.is_symlink() or index.is_symlink() or not 0<database.stat().st_size<=512*1024**2
            or not 0<index.stat().st_size<=1024**2):
        raise ValueError('feature_graph_input_budget')
    provenance=json.loads(index.read_bytes());rows=provenance['images']
    if not 2<=len(rows)<=240:raise ValueError('feature_graph_view_budget')
    times={Path(row['image']).name:row['relative_ticks_90k']/90000 for row in rows}
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        names=dict(db.execute('SELECT image_id,name FROM images'))
        if set(names.values())!=set(times):raise ValueError('feature_graph_index_binding')
        configurations={CONFIGS.get(config,str(config)):count for config,count in
                        db.execute('SELECT config,COUNT(*) FROM two_view_geometries GROUP BY config')}
        points={identity:np.frombuffer(raw,dtype='<f4').reshape(count,columns)
                for identity,count,columns,raw in db.execute('SELECT image_id,rows,cols,data FROM keypoints')}
        ids=sorted(names,key=lambda identity:times[names[identity]])
        adjacency={tuple(sorted(pair)) for pair in zip(ids,ids[1:])}
        motion=[];right=[];pairs=[]
        records=db.execute('SELECT pair_id,rows,cols,data FROM matches').fetchall()
        if len(records)>3000:raise ValueError('feature_graph_pair_budget')
        for identity,count,columns,raw in records:
            a,b=divmod(identity,PAIR_BASE)
            if (a,b) not in adjacency:continue
            if columns!=2 or count>20000:raise ValueError('feature_graph_match_budget')
            matches=np.frombuffer(raw or b'',dtype='<u4').reshape(count,columns)
            xy=points[a][matches[:,0],:2];uv=points[b][matches[:,1],:2]
            distance=np.linalg.norm(xy-uv,axis=1);motion.extend(distance.tolist())
            # A diagnostic region only, not semantic HUD classification.
            region=(xy[:,0]>=.77*provenance['geometry'][0])&(xy[:,1]>=.37*provenance['geometry'][1])
            right.extend(distance[region].tolist())
            pairs.append(dict(first=names[a],second=names[b],first_seconds=times[names[a]],
                              second_seconds=times[names[b]],raw_matches=count))
    def distribution(values):
        return dict(observations=len(values),median_displacement_px=float(np.median(values)) if values else None,
                    fraction_below_1_5px=float(np.mean(np.asarray(values)<1.5)) if values else None)
    return dict(schema='sphere-feature-graph-audit-v1',source_manifest_sha256=provenance['source_manifest_sha256'],
        index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),verified_configurations=configurations,
        adjacent_matches=distribution(motion),right_overlay_region=distribution(right),adjacent_pairs=pairs,
        stationary_threshold_is_diagnostic=True,source_modified=False,physical_actions=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('exclusive_output_required')
    write_json(args.output,audit(args.prepared))


if __name__=='__main__':main()
