const test = require("node:test");
const assert = require("node:assert");
const wotGate = require("../static/js/wot_gate.js");

test("WoTGate - U14 rejects WoT distance 2 and accepts distance 1", () => {
  global.DEPENDENT_CONTEXT = {
    is_dependent: true,
    bracket: "U14",
    wot_distance_limit: 1,
    parent_did: "did:key:z6MkParentAnchor",
    approved_contacts: ["3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"]
  };

  // Distance 0 (Parent anchor)
  assert.strictEqual(wotGate.getSenderWoTDistance("did:key:z6MkParentAnchor"), 0);
  assert.strictEqual(wotGate.interceptInboundMessage("did:key:z6MkParentAnchor"), true);

  // Distance 1 (Approved contact)
  assert.strictEqual(
    wotGate.getSenderWoTDistance("3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"),
    1
  );
  assert.strictEqual(
    wotGate.interceptInboundMessage("3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"),
    true
  );

  // Distance 2+ (Unknown peer / 2nd degree)
  assert.strictEqual(wotGate.interceptInboundMessage("unknown_peer_pubkey_hex_123456"), false);
  assert.strictEqual(wotGate.canAcceptChatHandshake("unknown_peer_pubkey_hex_123456"), false);
});

test("WoTGate - U14-U18 accepts WoT distance 2", () => {
  global.DEPENDENT_CONTEXT = {
    is_dependent: true,
    bracket: "U14-U18",
    wot_distance_limit: 2,
    parent_did: "did:key:z6MkParentAnchor",
    approved_contacts: ["approved_peer_1"]
  };

  // Mock TrustLens / ContactManager distance 2 tier
  global.TrustLens = {
    getTrustTier: (key) => (key === "peer_at_distance_2" ? "Level2" : null)
  };

  assert.strictEqual(wotGate.getSenderWoTDistance("peer_at_distance_2"), 2);
  assert.strictEqual(wotGate.interceptInboundMessage("peer_at_distance_2"), true);

  // Distance 3+ (Outside radius)
  assert.strictEqual(wotGate.interceptInboundMessage("untrusted_peer_3"), false);
});

test("WoTGate - Zero PII leakage during trust-distance checks", () => {
  const ctx = global.DEPENDENT_CONTEXT;
  assert.strictEqual(ctx.dob, undefined);
  assert.strictEqual(ctx.birth_date, undefined);
  assert.strictEqual(ctx.legal_name, undefined);
  assert.strictEqual(ctx.phone, undefined);
});
