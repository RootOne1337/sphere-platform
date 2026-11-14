"""Offline comparison of a route-local shortlist within the three-LK budget."""

from __future__ import annotations

import time

from motor_worker.route_confirmation import ReferenceLKConfirmationLocalizer
from scripts.pilot.check_route_coarse_retrieval import evaluate_reference


class CausalReferenceLocalizer(ReferenceLKConfirmationLocalizer):
    """Use prior pose only to select which recorded views to match on this image."""

    def __init__(self, *args, start_mode, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_mode = start_mode
        self._has_localized = False

    def observe(self, frame, **kwargs):
        pose = super().observe(frame, **kwargs)
        self._has_localized |= pose.state == "localized"
        return pose

    def _shortlist(self, scores):
        np = self.np
        rank = np.argsort(scores, kind="stable").tolist()
        if self.previous is not None and self.confirmations >= 3:
            _, _, progress, previous_time = self.previous
            age = self.last_received - previous_time
            if 0 < age <= 0.5:
                source_time = np.interp(progress, self.cumulative, self.reference_times)
                target = source_time + age
                # Projected source time is a search hint. PnP on the current
                # RGB and the original temporal gates still decide the pose.
                distance = np.abs(self.reference_times - target)
                local = np.argsort(distance, kind="stable")[:2].tolist()
                if distance[local[-1]] <= 0.5:
                    candidates = [rank[0], *local, *rank[1:3]]
                    return list(dict.fromkeys(candidates))[:3], "recent_pose"
        if self.start_mode == "beginning" and not self._has_localized:
            early_time = self.reference_times[0] + 5.0
            early_arc = min(0.15 * self.cumulative[-1],
                            np.interp(early_time, self.reference_times, self.cumulative))
            early = next((at for at in rank if self.reference_times[at] <= early_time
                          and self.cumulative[at] <= early_arc), None)
            if early is not None:
                candidates = [*rank[:2], early, rank[2]]
                return list(dict.fromkeys(candidates))[:3], "explicit_start"
        return rank[:3], "global"

    def _solve(self, *_unused):
        began = time.perf_counter()
        scores = self.np.mean((self._tiny - self._thumbnail(self._gray)) ** 2, axis=1)
        rank, scope = self._shortlist(scores)
        self.last_diagnostic.update(method="diagnostic_causal_reference_lk", candidateReferenceIndices=rank,
                                    causalSearchScope=scope, coarseSearchMs=(time.perf_counter() - began) * 1000)
        proposals, retained = [], []
        for index in rank:
            if self.clock() - self.last_received >= 0.25:
                break
            count, pose = evaluate_reference(self, self._gray, index)
            retained.append(count)
            if pose is not None:
                proposals.append(pose[:4])
        self.last_diagnostic.update(flowRetainedByCandidate=retained, verifiedCandidateCount=len(proposals),
                                    candidateMatchPnPMs=(time.perf_counter() - began) * 1000)
        return self._rank_proposals(proposals) if proposals else None
