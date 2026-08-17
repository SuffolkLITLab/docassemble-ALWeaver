# Grouping PDF checkboxes into one question

Most court forms offer a choice as a row of separate checkboxes: three boxes for
three ways of serving papers, one box per kind of relief. Each box is its own
PDF field, so the Weaver used to write a separate yes/no question for each one,
and the finished interview asked three questions where the form asks one.

Name the fields `parent+option` and the Weaver treats them as a single
question:

| PDF field name             | Meaning                                       |
|----------------------------|-----------------------------------------------|
| `service_method+by_mail`   | the `by_mail` option of `service_method`      |
| `service_method+in_hand`   | the `in_hand` option of `service_method`      |
| `service_method+by_email`  | the `by_email` option of `service_method`     |

The Weaver reads those three fields as one variable, `service_method`, with
three choices:

```yaml
- "Service method": service_method
  input type: radio
  choices:
    - By mail: by_mail
    - In hand: in_hand
    - By email: by_email
```

and ticks the right box in the attachment:

```yaml
- "service_method+by_mail": ${ service_method == 'by_mail' }
- "service_method+in_hand": ${ service_method == 'in_hand' }
- "service_method+by_email": ${ service_method == 'by_email' }
```

## Letting the user pick more than one

The guess is a radio button, because most grouped checkboxes on a form are
mutually exclusive. If more than one can be true, change the field's type to
**Checkboxes** on the "Choose field types" screen. The attachment switches to
reading each option out of the answer:

```yaml
- "relief_sought+rent": ${ relief_sought['rent'] }
- "relief_sought+utilities": ${ relief_sought['utilities'] }
```

## Notes

* `+` is not legal in a Python identifier, so it can never be confused with
  part of a variable name. Only the first `+` separates; anything after it is
  part of the option.
* Only the half before the `+` is a variable name, so the usual AssemblyLine
  labels still work: `user_address_county+suffolk` fills
  `users[0].address.county`.
* The option becomes both the stored value and, title-cased with underscores
  turned into spaces, the label the user sees. `by_mail` shows as "By mail".
  Edit the choices on the field-types screen if you want different wording.
* Turn off "normalize field names" when you upload, or FormFyxer may rewrite
  the names before the Weaver sees them.
