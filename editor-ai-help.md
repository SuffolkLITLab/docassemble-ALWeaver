# AI help on a field in `/al/editor`

A field can ask AI to help the person answer it. The person answers the field,
gives permission, and sees what AI suggests on a review screen where they can
change it. The answer they confirm is the one the interview keeps; their
original answer is kept too.

## Adding it

- In a question's field list, choose a kind of AI help from the top of the
  field's **Type** menu, or use **Add AI field**.
- The dialog has the settings an author usually needs: the kind of help, the
  field's label and variable, what AI should do, and the review screen's
  question and variable. Less common settings (extra instructions, other
  answers to send, a model, and whether to ask permission) are under
  **Advanced settings**.
- The field row then shows the kind of help as its type, and a line under it
  links to the review screen and to the declaration that holds the settings.
  The wand button reopens the dialog.

| Kind of help | What the review screen shows | ALToolbox call |
| --- | --- | --- |
| Improve writing | A text area with the rewritten answer | `chat_completion` |
| Ask follow-up questions until a goal is met | A text area with one answer written from all the replies | `GoalOrientedQuestionList` |
| Apply a custom prompt | A text area with the result | `chat_completion` |
| Summarize | A text area with the summary | `chat_completion` |
| Translate | A text area with the translation | `translate_text` |
| Find answers in text | One typed field per answer to find | `extract_fields_from_text` |
| Find answers in a document | One typed field per answer to find | `extract_fields_from_file` |
| Suggest a choice | Radio buttons with AI's pick selected | `classify_text` |

## What it writes

One save writes ordinary source, through `POST /al/editor/api/ai-assist`
(`editor_ai_assist.py`):

1. An `objects:` entry, `<field>_ai: AIAssist.using(...)`, holding the
   settings as literals. It joins the block that already declares AI help, or
   the first objects block.
2. `docassemble.ALToolbox:ai_assist.yml` in an `include:` block. It supplies
   the permission screen and skips it when the server has no AI service or
   the author turned it off.
3. A review question right after the question with the field. Its fields
   default to `${ <name>.suggestion(...) }`; its subquestion shows
   `${ <name>.review_note() }`.
4. The review question's variable in the interview order, on the line after
   the one that asks the question with the field. If the order doesn't ask
   that question, nothing is guessed and the dialog says so.

Editing changes the declaration in place. On the review question only the
`question` and `fields` keys are rewritten, and only when they change; the
subquestion and anything else the author added stay as written, and settings
added to a review field (`required`, `help`, ...) stay with its variable.
Renaming the reviewed answer renames its line in the interview order.
**Remove AI help** deletes the declaration, the review question and its order
line (leaving `pass` if that line was alone in an `if` or `for`); the field
and the include stay.

A declaration whose settings use Python expressions is shown, but the dialog
won't save over it: edit it in YAML.

## The interview order

In the order builder, the two lines read as one **AI help** step: *Ask* the
question, then *Review* it. The step moves as a unit, **Edit** opens the AI
help dialog, and the step menu links to both questions. **Add step → AI help
(ask, then review)** adds the pair for a field that already has AI help.
In the code the step is still the two lines, written back with their comments.

## At runtime

`AIAssist` (ALToolbox `ai_assist.py`) reads the field's answer first, then
asks permission, so the permission screen follows the answer it describes.
It sends only the field's answer (plus any answers the author listed), and
remembers each result per input, failures included, so redisplaying or
resuming doesn't repeat a paid call. If the person declines or the call
fails, the review screen starts from their own answer, or empty for
extraction. Extraction only fills the variables the author declared, and only
with plain values; a choice must be one of the author's choices.
