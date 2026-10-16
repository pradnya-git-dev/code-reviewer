from dotenv import load_dotenv
import sys
import anthropic
import json
from helpers import ROOT, first_text, parse_diff

# Loads variables from .env into system environment variables
load_dotenv() 

MODEL = "claude-sonnet-5"
CONFIDENCE_FLOOR = 0.7

client = anthropic.Anthropic()        						# Reads ANTHROPIC_API_KEY
review_response_schema = json.load(open(ROOT / "schemas" / "findings.json"))
rubric = open(ROOT / "prompts" / "system.md").read()

def review_diff(diff_text, feedback=None):
	prompt = "Review this diff:\n\n" + diff_text
	
	if feedback:
		prompt += "\n\nThe following issues were identified with your previous response. Address them:\n"
		for issue in feedback:
			prompt += "- " + issue + "\n"
	
	response = client.messages.create(
		model=MODEL,
		max_tokens=1024,										# Max token limit for the response
		system=rubric,
		messages=[
			{
				"role": "user",
				"content": prompt
			}
		],
		output_config={
			"format": {
				"type": "json_schema",
				"schema": review_response_schema
			}
		}
	)

	if response.stop_reason in ("refusal", "max_tokens"):
		raise RuntimeError("Incomplete response, stop_reason=", response.stop_reason)

	return json.loads(first_text(response))["findings"]


def validate(findings, visible):
	# "visible" maps each file in the diff to the line numbers the diff shows
	issues = []
	for finding in findings:
		file, line_number = finding["file"], finding["line_number"]
		if file not in visible:
			issues.append(f"File {file} is not in this diff.")
		elif line_number not in visible[file]:
			issues.append(f"File {file}, line {line_number} is not in this diff.")
	return issues


def keep_trustworthy(findings, visible):
	keep = []
	for finding in findings:
		in_diff = finding["file"] in visible and finding["line_number"] in visible[finding["file"]]
		sure_enough = finding["confidence"] >= CONFIDENCE_FLOOR
		if in_diff and (sure_enough or finding["severity"] == "CRITICAL"):
			keep.append(finding)
	return keep


def review_with_retry(diff_text):
	visible = parse_diff(diff_text)
	findings = review_diff(diff_text)
	issues = validate(findings, visible)
	if issues:	# Retry once and say what was wrong
		print("Retrying once: ", issues, file=sys.stderr)
		findings = review_diff(diff_text, feedback=issues)
	return keep_trustworthy(findings, visible)


if __name__ == "__main__":
	for finding in review_with_retry(open(sys.argv[1]).read()):
		print(f"[{finding['severity']}] {finding['file']}:{finding['line_number']} confidence:{finding['confidence']:.2f}")
		print(f"    {finding['issue']}")
		print(f"    fix: {finding['suggestion']}")