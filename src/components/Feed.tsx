/**
 * src/components/Feed.tsx — Dependent Feed Filtering Policy & Selector (DEP-202 & DEP-203)
 *
 * Enforces client-side WoT graph distance and age-bracket boundaries inside iyou_wun
 * so dependent users only receive permitted feed items per the 5-Year Trust Ladder.
 */

import React from "react";
import { DependentContext, WOT_DISTANCE_LIMITS } from "../auth/session";

export interface FeedNote {
  id: string;
  pubkey: string;
  author_pubkey?: string;
  author_did?: string;
  content: string;
  created_at: number;
  kind: number;
  wot_distance?: number;
  author_wot_distance?: number;
  trust_tier?: string;
  trust_level?: string;
  tags?: string[][];
  [key: string]: any;
}

export interface FeedFilterProps {
  notes: FeedNote[];
  dependentContext: DependentContext;
  viewerId?: string;
  trustGraph?: Record<string, string[]>;
  activeCircle?: string;
}

export function isFeedCircleAllowed(circle: string, dependentContext: DependentContext): boolean {
  if (!dependentContext || !dependentContext.is_dependent) {
    return true;
  }
  const bracket = (dependentContext.bracket || "ADULT").toUpperCase();
  const c = (circle || "").trim().toLowerCase();
  if (bracket === "U14" && (c === "global" || c === "public" || c === "world")) {
    return false;
  }
  return true;
}

export function calculateWoTDistance(
  authorId: string,
  viewerId?: string,
  trustGraph?: Record<string, string[]>,
  parentDid?: string | null,
  approvedContacts?: string[],
  note?: FeedNote
): number {
  const author = (authorId || "").trim().toLowerCase();
  const viewer = (viewerId || "").trim().toLowerCase();
  const parent = (parentDid || "").trim().toLowerCase();

  if (!author) return Infinity;
  if ((viewer && author === viewer) || (parent && author === parent)) {
    return 0;
  }

  if (note) {
    if (typeof note.wot_distance === "number") return note.wot_distance;
    if (typeof note.author_wot_distance === "number") return note.author_wot_distance;
  }

  const approvedSet = new Set((approvedContacts || []).map(c => c.trim().toLowerCase()));
  if (approvedSet.has(author)) {
    return 1;
  }

  if (note && (note.trust_tier === "Level0" || note.trust_tier === "Level0_5" || note.trust_level === "Level0" || note.trust_level === "Level0_5")) {
    return 1;
  }

  if (trustGraph) {
    const startNodes = new Set<string>();
    if (viewer) startNodes.add(viewer);
    if (parent) startNodes.add(parent);
    approvedSet.forEach(n => startNodes.add(n));

    if (startNodes.has(author)) return 1;

    // BFS
    const visited = new Set<string>(startNodes);
    const queue: [string, number][] = Array.from(startNodes).map(node => [node, 1]);

    while (queue.length > 0) {
      const [curr, dist] = queue.shift()!;
      if (curr === author) return dist;
      if (dist >= 4) continue;

      const neighbors = trustGraph[curr] || [];
      for (const n of neighbors) {
        const normN = n.trim().toLowerCase();
        if (normN === author) return dist + 1;
        if (!visited.has(normN)) {
          visited.add(normN);
          queue.push([normN, dist + 1]);
        }
      }
    }
  }

  return Infinity;
}

export function filterFeedForDependent(
  notes: FeedNote[],
  dependentContext: DependentContext,
  viewerId?: string,
  trustGraph?: Record<string, string[]>
): FeedNote[] {
  if (!dependentContext || !dependentContext.is_dependent) {
    return notes;
  }

  const bracket = dependentContext.bracket || "ADULT";
  const wotLimit = dependentContext.wot_distance_limit ?? WOT_DISTANCE_LIMITS[bracket] ?? Infinity;
  const parentDid = dependentContext.parent_did;
  const approved = dependentContext.approved_contacts || [];

  return notes.filter(note => {
    const author = note.pubkey || note.author_pubkey || note.author_did || "";
    const dist = calculateWoTDistance(author, viewerId, trustGraph, parentDid, approved, note);
    return dist <= wotLimit;
  });
}

export function isPublicPublishingSuppressed(kind: number, dependentContext: DependentContext): boolean {
  if (!dependentContext || !dependentContext.is_dependent) return false;
  const bracket = (dependentContext.bracket || "ADULT").toUpperCase();
  if (bracket === "U14" && (kind === 0 || kind === 1)) {
    return true;
  }
  return false;
}

export function getAllowedPublishingRelays(
  kind: number,
  relays: string[],
  dependentContext: DependentContext
): string[] {
  if (!isPublicPublishingSuppressed(kind, dependentContext)) {
    return relays;
  }
  return relays.filter(r => r.includes("127.0.0.1") || r.includes("localhost"));
}

export const Feed: React.FC<FeedFilterProps> = ({
  notes,
  dependentContext,
  viewerId,
  trustGraph,
  activeCircle = "iyou",
}) => {
  if (!isFeedCircleAllowed(activeCircle, dependentContext)) {
    return <div className="feed-empty-state">Global timeline is disabled for your trust bracket.</div>;
  }

  const filtered = filterFeedForDependent(notes, dependentContext, viewerId, trustGraph);

  if (filtered.length === 0) {
    return <div className="feed-empty-state">No notes found within your Web-of-Trust perimeter.</div>;
  }

  return (
    <div className="feed-stream">
      {filtered.map(note => (
        <article key={note.id} className="feed-note-card" data-pubkey={note.pubkey}>
          <div className="note-content">{note.content}</div>
        </article>
      ))}
    </div>
  );
};

export default Feed;
