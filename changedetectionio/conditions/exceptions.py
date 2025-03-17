class EmptyConditionRuleRowNotUsable(Exception):
    def __init__(self):
        super().__init__("One of the 'conditions' rulesets is incomplete, cannot run.")

    def __str__(self):
        return self.args[0]