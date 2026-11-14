/** Pure helpers for dictating a question. The browser does the listening (Web Speech API), so there
 *  is no server call, no key and no cost; this file only decides what is supported, which language
 *  to listen for, and how spoken text joins what the owner already typed. */

export function speechRecognitionCtor(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return null;
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
}

export const isVoiceSupported = (win) => speechRecognitionCtor(win) !== null;

/** The UI language picks the dictation language. Arabic dictation defaults to Egyptian Arabic. */
export function recognitionLang(uiLang) {
  return uiLang === "en" ? "en-US" : "ar-EG";
}

/** Append spoken text to the draft with one space between them; never drops what was typed. */
export function mergeDictation(base, spoken) {
  const b = (base ?? "").replace(/\s+$/, "");
  const s = (spoken ?? "").replace(/\s+/g, " ").trim();
  if (!s) return base ?? "";
  return b ? `${b} ${s}` : s;
}

/** Collapse a SpeechRecognition result list into { final, interim } text. */
export function readResults(results, fromIndex = 0) {
  let final = "";
  let interim = "";
  for (let i = fromIndex; i < results.length; i += 1) {
    const r = results[i];
    const text = r[0]?.transcript ?? "";
    if (r.isFinal) final += text;
    else interim += text;
  }
  return { final, interim };
}

/** Map a recognition error code to an i18n key, or null when it needs no message (user stopped). */
export function voiceErrorKey(code) {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "salesAssistant.voiceDenied";
    case "no-speech":
      return "salesAssistant.voiceNoSpeech";
    case "audio-capture":
      return "salesAssistant.voiceNoMic";
    case "aborted":
      return null;
    default:
      return "salesAssistant.voiceFailed";
  }
}
