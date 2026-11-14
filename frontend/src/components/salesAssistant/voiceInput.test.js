import { describe, expect, it } from "vitest";
import { isVoiceSupported, mergeDictation, readResults, recognitionLang, speechRecognitionCtor, voiceErrorKey } from "./voiceInput";

describe("voice support", () => {
  it("is unsupported with no window or no API", () => {
    expect(isVoiceSupported({})).toBe(false);
    expect(speechRecognitionCtor(undefined) === null || typeof window !== "undefined").toBe(true);
  });
  it("accepts the standard and the webkit constructor", () => {
    const A = function A() {};
    expect(speechRecognitionCtor({ SpeechRecognition: A })).toBe(A);
    expect(speechRecognitionCtor({ webkitSpeechRecognition: A })).toBe(A);
    expect(isVoiceSupported({ webkitSpeechRecognition: A })).toBe(true);
  });
});

describe("recognitionLang", () => {
  it("listens in Egyptian Arabic for the Arabic UI and English for English", () => {
    expect(recognitionLang("ar")).toBe("ar-EG");
    expect(recognitionLang("en")).toBe("en-US");
    expect(recognitionLang(undefined)).toBe("ar-EG");
  });
});

describe("mergeDictation", () => {
  it("keeps what was typed and adds the spoken text after one space", () => {
    expect(mergeDictation("كام بعت", "النهارده")).toBe("كام بعت النهارده");
  });
  it("does not double the space when the draft ends with whitespace", () => {
    expect(mergeDictation("كام بعت  ", "النهارده")).toBe("كام بعت النهارده");
  });
  it("uses the spoken text alone on an empty draft", () => {
    expect(mergeDictation("", "أهلا")).toBe("أهلا");
    expect(mergeDictation(undefined, "أهلا")).toBe("أهلا");
  });
  it("leaves the draft untouched when nothing was said", () => {
    expect(mergeDictation("مكتوب", "  ")).toBe("مكتوب");
    expect(mergeDictation("مكتوب", "")).toBe("مكتوب");
  });
  it("squeezes runs of spaces inside the spoken text", () => {
    expect(mergeDictation("", "كام   بعت")).toBe("كام بعت");
  });
});

describe("readResults", () => {
  const res = (text, isFinal) => Object.assign([{ transcript: text }], { isFinal });
  it("splits final from interim and starts at the given index", () => {
    const list = [res("أول ", true), res("تاني ", true), res("جاري", false)];
    expect(readResults(list)).toEqual({ final: "أول تاني ", interim: "جاري" });
    expect(readResults(list, 1)).toEqual({ final: "تاني ", interim: "جاري" });
  });
  it("is empty for an empty list", () => {
    expect(readResults([])).toEqual({ final: "", interim: "" });
  });
});

describe("voiceErrorKey", () => {
  it("maps permission, silence and mic problems to their own message", () => {
    expect(voiceErrorKey("not-allowed")).toBe("salesAssistant.voiceDenied");
    expect(voiceErrorKey("service-not-allowed")).toBe("salesAssistant.voiceDenied");
    expect(voiceErrorKey("no-speech")).toBe("salesAssistant.voiceNoSpeech");
    expect(voiceErrorKey("audio-capture")).toBe("salesAssistant.voiceNoMic");
  });
  it("stays silent when the owner stopped it and says failed otherwise", () => {
    expect(voiceErrorKey("aborted")).toBeNull();
    expect(voiceErrorKey("network")).toBe("salesAssistant.voiceFailed");
  });
});
