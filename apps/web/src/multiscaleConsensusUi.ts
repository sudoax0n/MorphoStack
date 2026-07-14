/** Pure gating for the default-off multi-scale consensus UI. */
export function multiscaleConsensusRequestValue(
  profile: string,
  hasObjectSeed: boolean,
  checkboxChecked: boolean,
  competitiveChecked: boolean
): boolean {
  return (
    (profile === "vesicle" || profile === "rbc") &&
    hasObjectSeed &&
    checkboxChecked &&
    !competitiveChecked
  );
}

export function multiscaleConsensusControlState(
  profile: string,
  hasObjectSeed: boolean,
  competitiveChecked: boolean
): { visible: boolean; enabled: boolean; reason: string } {
  if (profile === "active_surfaces") {
    return { visible: false, enabled: false, reason: "Not available for active surfaces." };
  }
  if (!hasObjectSeed) {
    return { visible: true, enabled: false, reason: "Select an object seed first." };
  }
  if (competitiveChecked) {
    return { visible: true, enabled: false, reason: "Turn off competitive tracking first." };
  }
  return { visible: true, enabled: true, reason: "" };
}

export function multiscaleConsensusField(state: {
  profile: string;
  hasObjectSeed: boolean;
  checkboxChecked: boolean;
  competitiveChecked: boolean;
}): { multiscale_consensus: boolean } {
  return {
    multiscale_consensus: multiscaleConsensusRequestValue(
      state.profile,
      state.hasObjectSeed,
      state.checkboxChecked,
      state.competitiveChecked
    )
  };
}
