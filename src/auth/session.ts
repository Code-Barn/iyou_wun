/**
 * src/auth/session.ts — Dependent Identity, Token Ingress & Session State (DEP-202 & DEP-203)
 *
 * Enforces client-side WoT graph distance and age-bracket boundaries inside iyou_wun
 * so dependent users only receive permitted feed items and direct messages per the
 * 5-Year Trust Ladder (OMNI-DEP-GRAD-SPEC-V1).
 */

export type DependentBracket = "U14" | "U14-U18" | "U18" | "ADULT";

export interface DependentContext {
  is_dependent: boolean;
  bracket: DependentBracket;
  wot_distance_limit: number;
  parent_did?: string | null;
  attestation_vc?: any;
  issued_at?: number | null;
  expires_at?: number | null;
  revoked: boolean;
  approved_contacts?: string[];
}

export const WOT_DISTANCE_LIMITS: Record<DependentBracket, number> = {
  "U14": 1,
  "U14-U18": 2,
  "U18": 3,
  "ADULT": Infinity,
};

export const DEFAULT_ADULT_CONTEXT: DependentContext = {
  is_dependent: false,
  bracket: "ADULT",
  wot_distance_limit: Infinity,
  parent_did: null,
  attestation_vc: null,
  issued_at: null,
  expires_at: null,
  revoked: false,
  approved_contacts: [],
};

function decodeJwtPayload(jwtToken: string): Record<string, any> {
  const parts = jwtToken.trim().split(".");
  if (parts.length !== 3) {
    throw new Error("Invalid JWT format");
  }
  let payloadB64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  const remainder = payloadB64.length % 4;
  if (remainder) {
    payloadB64 += "=".repeat(4 - remainder);
  }
  if (typeof atob === "function") {
    return JSON.parse(atob(payloadB64));
  } else if (typeof Buffer !== "undefined") {
    return JSON.parse(Buffer.from(payloadB64, "base64").toString("utf-8"));
  }
  throw new Error("Base64 decoding not available");
}

export function parseDependentClaim(
  idTokenOrClaims: string | Record<string, any> | null | undefined
): DependentContext {
  if (!idTokenOrClaims) {
    return { ...DEFAULT_ADULT_CONTEXT };
  }

  let claims: Record<string, any>;
  if (typeof idTokenOrClaims === "string") {
    claims = decodeJwtPayload(idTokenOrClaims);
  } else if (typeof idTokenOrClaims === "object") {
    claims = idTokenOrClaims;
  } else {
    throw new Error("Unsupported token/claims type");
  }

  const dep = claims.dep && typeof claims.dep === "object" ? claims.dep : ("bracket" in claims ? claims : null);
  if (!dep) {
    return { ...DEFAULT_ADULT_CONTEXT };
  }

  if (dep.revoked === true) {
    throw new Error("Dependent attestation has been revoked by guardian.");
  }

  if (dep.expires_at != null) {
    const nowSec = Math.floor(Date.now() / 1000);
    if (nowSec > Number(dep.expires_at)) {
      throw new Error("Dependent attestation has expired.");
    }
  }

  const rawBracket = String(dep.bracket || "ADULT").trim().toUpperCase() as DependentBracket;
  const bracket: DependentBracket = (rawBracket in WOT_DISTANCE_LIMITS) ? rawBracket : "U14";
  const is_dependent = dep.is_dependent != null ? Boolean(dep.is_dependent) : bracket !== "ADULT";
  const wot_distance_limit = WOT_DISTANCE_LIMITS[bracket] ?? Infinity;

  const approved = Array.isArray(dep.approved_contacts)
    ? dep.approved_contacts.map((c: any) => String(c).trim().toLowerCase()).filter(Boolean)
    : [];

  return {
    is_dependent,
    bracket,
    wot_distance_limit,
    parent_did: dep.parent_did || null,
    attestation_vc: dep.attestation_vc || null,
    issued_at: dep.issued_at != null ? Number(dep.issued_at) : null,
    expires_at: dep.expires_at != null ? Number(dep.expires_at) : null,
    revoked: false,
    approved_contacts: approved,
  };
}

export function storeDependentContext(
  storageOrSession: any,
  tokenOrClaims: string | Record<string, any>
): DependentContext {
  const context = parseDependentClaim(tokenOrClaims);
  if (storageOrSession) {
    if (typeof storageOrSession.setItem === "function") {
      storageOrSession.setItem("wun_dependent_context", JSON.stringify(context));
    } else {
      storageOrSession.dependent_context = context;
      storageOrSession.is_dependent = context.is_dependent;
      storageOrSession.bracket = context.bracket;
      storageOrSession.wot_distance_limit = context.wot_distance_limit;
      storageOrSession.parent_did = context.parent_did;
    }
  }
  if (typeof window !== "undefined") {
    (window as any).DEPENDENT_CONTEXT = context;
  }
  return context;
}

export function getDependentContext(storageOrSession?: any): DependentContext {
  if (storageOrSession) {
    if (typeof storageOrSession.getItem === "function") {
      const stored = storageOrSession.getItem("wun_dependent_context");
      if (stored) {
        try {
          return JSON.parse(stored);
        } catch {
          /* ignore */
        }
      }
    } else if (storageOrSession.dependent_context) {
      return storageOrSession.dependent_context;
    }
  }
  if (typeof window !== "undefined" && (window as any).DEPENDENT_CONTEXT) {
    return (window as any).DEPENDENT_CONTEXT;
  }
  return { ...DEFAULT_ADULT_CONTEXT };
}
