import { describe, expect, it } from "vitest";
import { mapIntegrations } from "@/hooks/useRealData";

const row = (over = {}) => ({ id: "i1", provider: "facebook", status: "connected", credentials_verified: true, ...over });
const facebook = (rows) => mapIntegrations(rows).find((c) => c.id === "facebook");

describe("the channel list carries the Facebook permissions a connection lacks", () => {
  it("lists the missing permissions of an old connection and keeps it connected", () => {
    const fb = facebook([row({ missing_scopes: ["pages_manage_posts", "read_insights"] })]);
    expect(fb.missingScopes).toEqual(["pages_manage_posts", "read_insights"]);
    expect(fb.connected).toBe(true); // chat keeps working: only posting, comments and insights need them
  });
  it("is empty for a fully permitted connection, an absent field, a bad field and no connection", () => {
    expect(facebook([row({ missing_scopes: [] })]).missingScopes).toEqual([]);
    expect(facebook([row()]).missingScopes).toEqual([]);
    expect(facebook([row({ missing_scopes: "pages_manage_posts" })]).missingScopes).toEqual([]);
    expect(facebook([]).missingScopes).toEqual([]);
    expect(facebook(null).connected).toBe(false);
  });
  it("still maps connection state as before", () => {
    const fb = facebook([row({ status: "active", credentials_verified: false, webhook_status: "receiving" })]);
    expect(fb).toMatchObject({ integrationId: "i1", connected: false, webhookStatus: "receiving", credentialsVerified: false });
  });
});
