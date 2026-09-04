/**
 * src/chat/wot_gate.ts — Inbound DM & Chat Filtering Gate (DEP-202 & DEP-203)
 *
 * Intercepts inbound Nostr encrypted DMs (kind:4 / NIP-04) and XMPP stanzas:
 * - Queries the local contact trust engine.
 * - Rejects inbound chat handshakes if the sender's graph distance exceeds wot_distance_limit.
 * - Drops unknown messages silently without alerting the minor or exposing message previews.
 * - Zero PII: verifies cryptographic graph distance only, no date of birth or legal identity.
 */

import { DependentContext, getDependentContext, WOT_DISTANCE_LIMITS } from "../auth/session";

export interface NostrEvent {
  id?: string;
  pubkey: string;
  kind: number;
  content: string;
  tags?: string[][];
  created_at?: number;
  sig?: string;
}

export interface XMPPStanza {
  from: string;
  to?: string;
  type?: string;
  body?: string;
  [key: string]: any;
}

export interface WoTFilterResult {
  allowed: boolean;
  distance: number;
  sender: string;
  reason?: string;
}

export interface ContactTrustEngine {
  getTrustDistance?: (sender: string) => Promise<number> | number;
  isApprovedContact?: (sender: string) => Promise<boolean> | boolean;
  getTrustTier?: (sender: string) => string | null;
  getCurrentContactList?: () => any[];
}

export class WoTGate {
  private getContext: () => DependentContext;
  private trustEngine?: ContactTrustEngine;

  constructor(options?: {
    getDependentContext?: () => DependentContext;
    trustEngine?: ContactTrustEngine;
  }) {
    this.getContext = options?.getDependentContext || getDependentContext;
    this.trustEngine = options?.trustEngine;
  }

  /**
   * Determine the sender's graph distance from the dependent / parent anchor.
   */
  public async getSenderWoTDistance(sender: string): Promise<number> {
    const normSender = (sender || "").trim().toLowerCase();
    if (!normSender) return Infinity;

    const ctx = this.getContext();
    const parentDid = (ctx.parent_did || "").toLowerCase();

    // Distance 0: Parent anchor or self
    if (parentDid && normSender === parentDid) {
      return 0;
    }

    // Direct approved contacts
    const approved = (ctx.approved_contacts || []).map(c => c.toLowerCase());
    if (approved.includes(normSender)) {
      return 1;
    }

    // Query custom trust engine if configured
    if (this.trustEngine) {
      if (typeof this.trustEngine.getTrustDistance === "function") {
        try {
          const d = await this.trustEngine.getTrustDistance(normSender);
          if (typeof d === "number" && !isNaN(d)) return d;
        } catch {
          /* fail closed */
        }
      }

      if (typeof this.trustEngine.isApprovedContact === "function") {
        try {
          const isAppr = await this.trustEngine.isApprovedContact(normSender);
          if (isAppr) return 1;
        } catch {
          /* fail closed */
        }
      }

      if (typeof this.trustEngine.getTrustTier === "function") {
        const tier = this.trustEngine.getTrustTier(normSender);
        if (tier === "Level0" || tier === "Level0_5" || tier === "Level1") {
          return 1;
        } else if (tier === "Level2") {
          return 2;
        }
      }
    }

    // Default unknown sender outside perimeter
    return Infinity;
  }

  /**
   * Intercept and evaluate an inbound Nostr Encrypted Direct Message (Kind 4 / NIP-04).
   * Rejects and drops silently if sender distance > wot_distance_limit.
   */
  public async evaluateInboundNostrDM(event: NostrEvent): Promise<WoTFilterResult> {
    if (!event || event.kind !== 4) {
      return { allowed: true, distance: 0, sender: event?.pubkey || "" };
    }

    const sender = event.pubkey;
    const ctx = this.getContext();

    if (!ctx.is_dependent) {
      return { allowed: true, distance: 0, sender };
    }

    const limit = ctx.wot_distance_limit ?? WOT_DISTANCE_LIMITS[ctx.bracket] ?? Infinity;
    const distance = await this.getSenderWoTDistance(sender);

    if (distance <= limit) {
      return { allowed: true, distance, sender };
    }

    return {
      allowed: false,
      distance,
      sender,
      reason: `WoT graph distance ${distance} exceeds limit ${limit} for bracket ${ctx.bracket}. Message dropped silently.`,
    };
  }

  /**
   * Intercept and evaluate an inbound XMPP stanza (message or subscription handshake).
   * Rejects handshakes and drops unknown messages silently.
   */
  public async evaluateInboundXMPP(stanza: XMPPStanza | string): Promise<WoTFilterResult> {
    let from = "";
    let isHandshake = false;

    if (typeof stanza === "string") {
      const fromMatch = stanza.match(/from=["']([^"']+)["']/i);
      from = fromMatch ? fromMatch[1] : "";
      isHandshake = stanza.includes("type='subscribe'") || stanza.includes('type="subscribe"');
    } else if (stanza && typeof stanza === "object") {
      from = stanza.from || "";
      isHandshake = stanza.type === "subscribe";
    }

    const cleanSender = from.split("/")[0].toLowerCase();
    const ctx = this.getContext();

    if (!ctx.is_dependent) {
      return { allowed: true, distance: 0, sender: cleanSender };
    }

    const limit = ctx.wot_distance_limit ?? WOT_DISTANCE_LIMITS[ctx.bracket] ?? Infinity;
    const distance = await this.getSenderWoTDistance(cleanSender);

    if (distance <= limit) {
      return { allowed: true, distance, sender: cleanSender };
    }

    return {
      allowed: false,
      distance,
      sender: cleanSender,
      reason: isHandshake
        ? `Inbound chat handshake rejected: sender distance ${distance} exceeds limit ${limit}.`
        : `Inbound XMPP message dropped silently: sender distance ${distance} exceeds limit ${limit}.`,
    };
  }

  /**
   * Universal message interceptor. Returns true if allowed, false if dropped.
   * Never throws or exposes sender content on rejection.
   */
  public async interceptInboundMessage(
    sender: string,
    messageType: "nostr" | "xmpp" = "nostr"
  ): Promise<boolean> {
    try {
      const ctx = this.getContext();
      if (!ctx.is_dependent) return true;

      const limit = ctx.wot_distance_limit ?? WOT_DISTANCE_LIMITS[ctx.bracket] ?? Infinity;
      const distance = await this.getSenderWoTDistance(sender);

      return distance <= limit;
    } catch {
      // Fail closed on error for minor protection
      return false;
    }
  }

  /**
   * Evaluate whether an inbound chat handshake should be accepted.
   */
  public async canAcceptChatHandshake(sender: string): Promise<boolean> {
    return this.interceptInboundMessage(sender);
  }
}

export const defaultWoTGate = new WoTGate();
export default defaultWoTGate;
