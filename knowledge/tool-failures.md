# Diagnostic failure handling

Retry a transient diagnostic failure at most once, counting it in the total tool budget of eight calls. The model budget is six calls and investigation deadline is 120 seconds; these are initial development bounds. If a required diagnostic remains unavailable, return incomplete or escalate and identify the missing check. Never invent a successful response, treat an error as healthy, or execute an unchecked fallback.
