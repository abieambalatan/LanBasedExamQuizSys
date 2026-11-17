/* TXT question format shared by the upload preview and question editor. */
const EXAM_PARTS = [
  { part: 1, type: "multiple_choice", label: "Multiple Choice" },
  { part: 2, type: "identification", label: "Identification" },
  { part: 3, type: "true_false", label: "True or False" },
  { part: 4, type: "matching", label: "Matching Type" },
];

function parseExamText(input) {
  if (typeof input !== "string" || !input.trim()) throw new Error("The TXT file is empty.");
  const questions = [];
  let part = 1;
  let current = null;
  let sharedChoices = [];
  let collectingChoices = false;
  const typeNames = {
    multiplechoice: 1, identification: 2, truefalse: 3, trueorfalse: 3,
    matching: 4, matchingtype: 4,
  };
  const fail = (line, message) => { throw new Error(`Line ${line}: ${message}`); };

  function finish() {
    if (!current) return;
    const q = current;
    if (!q.text.trim()) fail(q.line, "Question text is missing.");
    if (!q.answer) fail(q.line, "Add an Answer: line for this question.");
    const definition = EXAM_PARTS[part - 1];
    let options = q.options;
    let correct = 0;
    let answerText = "";
    if (definition.type === "identification") {
      if (options.length) fail(q.line, "Identification questions use Answer: text, without choices.");
      answerText = q.answer.toUpperCase();
    } else if (definition.type === "true_false") {
      if (options.length && (options.length !== 2 || options[0].toLowerCase() !== "true" || options[1].toLowerCase() !== "false")) {
        fail(q.line, "True or False choices must be A. True and B. False, or omit the choices.");
      }
      options = ["True", "False"];
      const answer = q.answer.toUpperCase();
      if (!["TRUE", "FALSE", "T", "F", "A", "B"].includes(answer)) fail(q.line, "Use Answer: True or Answer: False.");
      correct = ["TRUE", "T", "A"].includes(answer) ? 0 : 1;
    } else {
      if (definition.type === "multiple_choice" && options.length !== 4) fail(q.line, "Multiple choice needs four choices, A-D.");
      if (definition.type === "matching" && (options.length < 2 || options.length > 26)) fail(q.line, "Matching Type needs 2-26 choices, or a shared Choices: list.");
      const letter = q.answer.toUpperCase();
      correct = /^[A-Z]$/.test(letter) ? letter.charCodeAt(0) - 65 : -1;
      if (correct < 0 || correct >= options.length) fail(q.line, "Answer must be a letter from this question's choices.");
    }
    questions.push({
      part, type: definition.type, text: q.text.trim(), options, correct,
      answerText, alternatives: q.alternatives,
    });
    current = null;
  }

  function start(text, line) {
    current = { text, line, answer: "", alternatives: [], options: part === 4 ? sharedChoices.slice() : [], ownChoices: false };
  }

  input.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").split("\n").forEach((raw, index) => {
    const line = raw.trim();
    const number = index + 1;
    if (!line) return;
    const heading = line.match(/^\[?\s*Part\s+(\d+|IV|III|II|I)\b.*?\]?$/i);
    const bareType = typeNames[line.replace(/[\s_\-\[\]:/]/g, "").toLowerCase()];
    if (heading || bareType) {
      finish();
      const roman = { I: 1, II: 2, III: 3, IV: 4 };
      const next = heading ? (roman[heading[1].toUpperCase()] || Number(heading[1])) : bareType;
      if (next < 1 || next > 4) fail(number, "Only Parts 1-4 are supported.");
      part = next;
      sharedChoices = [];
      collectingChoices = false;
      return;
    }
    const typeLine = line.match(/^Type\s*:\s*(.+)$/i);
    if (typeLine) {
      finish();
      const next = typeNames[typeLine[1].replace(/[\s_\-/]/g, "").toLowerCase()];
      if (!next) fail(number, "Unknown question type.");
      part = next;
      collectingChoices = false;
      return;
    }
    if (/^(Choices|Column\s+B)\s*:\s*$/i.test(line)) {
      finish();
      if (part !== 4) fail(number, "Shared Choices: lists belong in Part 4 - Matching Type.");
      sharedChoices = [];
      collectingChoices = true;
      return;
    }
    const question = line.match(/^(?:Question\s*:\s*|\d+\s*[.)-]\s*)(.+)$/i);
    if (question) {
      finish();
      start(question[1], number);
      collectingChoices = false;
      return;
    }
    const option = line.match(/^([A-Z])\s*[.)]\s*(.+)$/i);
    if (option) {
      const target = collectingChoices ? sharedChoices : current?.options;
      if (!target) fail(number, "Put choices after a Question: line or a shared Choices: heading.");
      if (current && !collectingChoices && !current.ownChoices) {
        current.options = [];
        current.ownChoices = true;
      }
      const choices = collectingChoices ? sharedChoices : current.options;
      if (option[1].toUpperCase().charCodeAt(0) - 65 !== choices.length) fail(number, "Label choices in order, starting with A.");
      choices.push(option[2].trim());
      return;
    }
    const answer = line.match(/^(?:Answer|Ans|Correct\s+Answer)\s*[:.)-]\s*(.+)$/i);
    if (answer) {
      if (!current) fail(number, "Put Answer: after a Question: line.");
      if (current.answer) fail(number, "This question already has an answer.");
      current.answer = answer[1].trim();
      return;
    }
    const alternatives = line.match(/^Alternatives?\s*:\s*(.*)$/i);
    if (alternatives) {
      if (!current || part !== 2) fail(number, "Alternatives: belongs after an identification question.");
      current.alternatives = alternatives[1].split(",").map(value => value.trim().toUpperCase()).filter(Boolean);
      return;
    }
    if (collectingChoices) fail(number, "Use lettered choices, then Question: for each matching item.");
    if (current && !current.answer) current.text += " " + line;
    else { finish(); start(line, number); }
  });
  finish();
  if (!questions.length) throw new Error("No questions found in the TXT file.");
  if (collectingChoices) throw new Error("The matching choices need at least one Question: and Answer: item.");
  return questions;
}
