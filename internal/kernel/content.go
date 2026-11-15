package kernel

func hasVisibleContent(value map[string]any) bool {
	choices, _ := value["choices"].([]any)
	for _, v := range choices {
		c, _ := v.(map[string]any)
		delta, _ := c["delta"].(map[string]any)
		text, _ := delta["content"].(string)
		if text != "" {
			return true
		}
	}
	return false
}
