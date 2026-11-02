# Shared UI components

Keep the existing FieldHQ appearance. Shared controls live in `static/panel.css`; feature styles own their layouts and specialized controls. Use the existing palette variables rather than hardcoded colors. Original keeps square corners; other themes retain their existing colors and shapes.

## Controls and spacing

The shared variables are `--ui-gap`, `--ui-control-height`, `--ui-control-padding`, `--ui-field-padding`, `--ui-radius` and `--ui-dialog-padding`. Desktop controls use the current compact sizing; mobile controls have a 40 px minimum height. Console controls, charts, range inputs, file pickers and color pickers retain their specialized styling.

Use `btn-save` for the main action, ordinary buttons for secondary actions and `btn-danger` for destructive actions. Preserve permission-controlled `hidden` attributes. Never infer permissions or action types from visible text.

## Headers and toolbars

Workspace headers use `fieldhq-brand`, `fieldhq-areas` and `fieldhq-account`. Help, account controls and Logout belong in the account group. Public login/signup and initial setup retain their focused layouts.

Use `unit-toolbar` or `ui-toolbar` for a wrapping toolbar. When a page has search/filters and actions, put them in `ui-toolbar-filters` and `ui-toolbar-actions`. Keep DOM order consistent with visual order. On phones, filters and actions wrap into separate rows. Existing server toolbars retain their current arrangements and use the same control sizing.

## Dialogs

Keep native `<dialog>` elements, labels, existing save handlers and unsaved-draft protection. Shared styles cover the existing unit, account, mod, fleet and instance dialogs. Dialog headers allow long titles to wrap; footers keep actions together. `PanelUI.confirm(message, title, destructive)` provides the shared confirmation dialog. A destructive confirmation starts with Cancel focused and uses the danger-styled Delete action.

## Tables, empty states and errors

Keep tables inside their existing scrolling wrappers and retain their column sizing and data presentation. `unit-table` supplies the unit table appearance. Do not globally right-align the last column; it may contain names or other text rather than actions.

Use `unit-empty` for empty-state text. Existing `role="alert"` error regions and `unit-inline-error` share the same readable border, spacing and theme colors. Empty/hidden alerts have no box. Keep error messages specific, retain drafts on failure and use existing retry handlers. Validation uses `aria-invalid="true"`; disabled fields and buttons have consistent visual states.

## Scope

This component pass changes presentation and confirmation dialogs only. Unit IDs, stored data, routes, backend permissions and workspace destinations remain independent of this styling layer. The separate platform administration workspace is a subsequent task.
