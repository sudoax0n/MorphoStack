/**
 * Packet 11 — experimental competitive tracking UI helpers (pure).
 *
 * Competitive mode is only supported for the vesicle + object-seed workflow.
 * Outside that state the request field must be forced false regardless of checkbox.
 */

export const COMPETITIVE_TRACKING_UI_WARNING =
  "Touching-vesicle real-data sign-off incomplete. Results require review and may not be publication-ready.";

export type CompetitiveUiState = {
  profile: string;
  hasObjectSeed: boolean;
  checkboxChecked: boolean;
};

/** True when the experimental control may be shown and may affect requests. */
export function isCompetitiveTrackingSupported(
  profile: string,
  hasObjectSeed: boolean
): boolean {
  return profile === "vesicle" && Boolean(hasObjectSeed);
}

/**
 * Value to send as ``competitive_tracking`` on preview/analyze/correction.
 * Always false for rbc/active_surfaces or when no seed is selected.
 */
export function competitiveTrackingRequestValue(
  profile: string,
  hasObjectSeed: boolean,
  checkboxChecked: boolean
): boolean {
  return (
    isCompetitiveTrackingSupported(profile, hasObjectSeed) && Boolean(checkboxChecked)
  );
}

/** UI visibility/disabled state for the experimental control. */
export function competitiveTrackingControlState(
  profile: string,
  hasObjectSeed: boolean
): { visible: boolean; enabled: boolean; reason: string } {
  if (profile !== "vesicle") {
    return {
      visible: false,
      enabled: false,
      reason: "Competitive tracking is only available in vesicle mode."
    };
  }
  if (!hasObjectSeed) {
    return {
      visible: true,
      enabled: false,
      reason: "Select an object seed before enabling competitive tracking."
    };
  }
  return { visible: true, enabled: true, reason: "" };
}

/**
 * Build the competitive_tracking field for request bodies (preview / analyze / correction).
 */
export function competitiveTrackingField(
  state: CompetitiveUiState
): { competitive_tracking: boolean } {
  return {
    competitive_tracking: competitiveTrackingRequestValue(
      state.profile,
      state.hasObjectSeed,
      state.checkboxChecked
    )
  };
}

/**
 * Correction request profile must come from the same control as the rest of the UI
 * (``profile-input``), never a missing element name.
 */
export function correctionProfileValue(
  profileInputValue: string | null | undefined,
  fallback: string = "vesicle"
): string {
  const v = String(profileInputValue ?? "").trim();
  if (v === "vesicle" || v === "rbc" || v === "active_surfaces") {
    return v;
  }
  return fallback;
}
