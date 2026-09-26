use serde_json::Map;
use serde_json::Value;

const SECRET_PARTS: &[&str] = &[
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "apikey",
    "authorization",
    "cookie",
    "signature",
    "jwt",
    "bearer",
    "privatekey",
    "clientsecret",
    "refresh",
];

const PII_PARTS: &[&str] = &[
    "email",
    "mobile",
    "phone",
    "nationalid",
    "taxid",
    "taxnumber",
    "iban",
    "bic",
    "cardnumber",
    "cvv",
    "ssn",
    "passportid",
    "address",
];

const REDACTED: &str = "[redacted]";
const MAX_STRING_CHARS: usize = 400;
const MAX_DEPTH: usize = 6;

pub fn render(message: &str, fields: &Value, request_id: Option<&str>) -> String {
    let fields = redact(fields, 0);

    match request_id {
        Some(id) => format!("{message} request_id={id} {fields}"),
        None => format!("{message} {fields}"),
    }
}

/// The Rust half of the same rule the UI applies: a credential or a piece of
/// customer PII never reaches a log file, and the fields support needs to trace a
/// request (`request_id`, `code`) survive.
pub fn redact(value: &Value, depth: usize) -> Value {
    if depth >= MAX_DEPTH {
        return Value::String("[max depth]".to_string());
    }

    match value {
        Value::String(text) => Value::String(redact_string(text)),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| redact(item, depth + 1))
                .collect::<Vec<Value>>(),
        ),
        Value::Object(entries) => {
            let mut out = Map::with_capacity(entries.len());

            for (key, item) in entries {
                let kept = if is_secret_key(key) || is_pii_key(key) {
                    Value::String(REDACTED.to_string())
                } else {
                    redact(item, depth + 1)
                };
                out.insert(key.clone(), kept);
            }

            Value::Object(out)
        }
        other => other.clone(),
    }
}

fn redact_string(text: &str) -> String {
    if carries_credential(text) {
        return REDACTED.to_string();
    }

    let count = text.chars().count();
    if count <= MAX_STRING_CHARS {
        return text.to_string();
    }

    let head: String = text.chars().take(MAX_STRING_CHARS).collect();
    let suffix = text.chars().skip(MAX_STRING_CHARS).collect::<String>();

    format!("{head}…[truncated {} chars]", suffix.chars().count())
}

fn carries_credential(text: &str) -> bool {
    let lowered = text.to_lowercase();

    lowered.contains("authorization:")
        || lowered.contains("x-api-key:")
        || lowered.contains("bearer ")
        || looks_like_token(&lowered)
}

fn looks_like_token(lowered: &str) -> bool {
    lowered.contains("eyJ") && lowered.matches('.').count() >= 2
}

fn normalise(key: &str) -> String {
    key.chars()
        .filter(char::is_ascii_alphabetic)
        .flat_map(|c| c.to_lowercase())
        .collect()
}

fn contains_any(name: &str, parts: &[&str]) -> bool {
    parts.iter().any(|part| name.contains(part))
}

fn is_secret_key(key: &str) -> bool {
    contains_any(&normalise(key), SECRET_PARTS)
}

fn is_pii_key(key: &str) -> bool {
    contains_any(&normalise(key), PII_PARTS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn redacts_a_credential_shaped_key() {
        let out = redact(&json!({ "access_token": "abc", "refresh_token": "abc" }), 0);

        assert_eq!(out["access_token"], json!(REDACTED));
        assert_eq!(out["refresh_token"], json!(REDACTED));
    }

    #[test]
    fn redacts_customer_pii_but_not_the_display_name() {
        let out = redact(&json!({ "mobile": "+201000000000", "name": "سارة" }), 0);

        assert_eq!(out["mobile"], json!(REDACTED));
        assert_eq!(out["name"], json!("سارة"));
    }

    #[test]
    fn keeps_the_fields_support_needs_to_trace_a_request() {
        let out = redact(&json!({ "request_id": "a1b2", "code": "rate_limited" }), 0);

        assert_eq!(out["request_id"], json!("a1b2"));
        assert_eq!(out["code"], json!("rate_limited"));
    }

    #[test]
    fn redacts_a_token_inside_a_free_text_value() {
        let out = redact(
            &json!({ "detail": ["ok", "decode failed eyJhbGci.eyJzdWI.YQ"] }),
            0,
        );

        assert_eq!(out["detail"][0], json!("ok"));
        assert_eq!(out["detail"][1], json!(REDACTED));
    }

    #[test]
    fn truncates_a_long_value_and_says_how_much_it_dropped() {
        let long = "x".repeat(500);
        let out = redact(&json!({ "body": long }), 0);
        let text = out["body"].as_str().unwrap_or_default();

        assert!(text.ends_with("[truncated 100 chars]"));
        assert_eq!(text.chars().count(), MAX_STRING_CHARS + 22);
    }

    #[test]
    fn stops_descending_at_the_depth_limit() {
        let mut nested = json!({ "leaf": "deep" });
        for _ in 0..(MAX_DEPTH + 3) {
            nested = json!({ "next": nested });
        }

        assert!(render("boot", &nested, None).contains("[max depth]"));
    }
}
