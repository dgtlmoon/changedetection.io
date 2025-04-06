# Condition Rule Form (for each rule row)
from wtforms import Form, SelectField, StringField, validators
from wtforms import validators

class ConditionFormRow(Form):

    # ✅ Ensure Plugins Are Loaded BEFORE Importing Choices
    from changedetectionio.conditions import plugin_manager
    from changedetectionio.conditions import operator_choices, field_choices
    field = SelectField(
        "Field",
        choices=field_choices,
        validators=[validators.Optional()]
    )

    operator = SelectField(
        "Operator",
        choices=operator_choices,
        validators=[validators.Optional()]
    )

    value = StringField("Value", validators=[validators.Optional()], render_kw={"placeholder": "A value"})

    def validate(self, extra_validators=None):
        # First, run the default validators
        if not super().validate(extra_validators):
            return False

        # Custom validation logic
        # If any of the operator/field/value is set, then they must be all set
        if any(value not in ("", False, "None", None) for value in [self.operator.data, self.field.data, self.value.data]):
            if not self.operator.data or self.operator.data == 'None':
                self.operator.errors.append("Operator is required.")
                return False

            if not self.field.data or self.field.data == 'None':
                self.field.errors.append("Field is required.")
                return False

            if not self.value.data:
                self.value.errors.append("Value is required.")
                return False

        return True  # Only return True if all conditions pass