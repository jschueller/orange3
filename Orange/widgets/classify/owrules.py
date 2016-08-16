from collections import OrderedDict
import numpy as np
from PyQt4.QtCore import Qt

from Orange.data import Table
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.classification.rules import (WeightedRelativeAccuracyEvaluator,
                                         LaplaceAccuracyEvaluator,
                                         EntropyEvaluator, _RuleClassifier,
                                         _RuleLearner)


class CustomRuleClassifier(_RuleClassifier):
    def __init__(self, domain, rule_list, params):
        super().__init__(domain, rule_list)
        assert params is not None

        self.rule_ordering = params["Rule ordering"]
        self.covering_algorithm = params["Covering algorithm"]
        self.params = params

    def predict(self, X):
        if (self.rule_ordering == "ordered" and
                self.covering_algorithm == "exclusive"):
            return self.ordered_predict(X)

        if (self.rule_ordering == "unordered" or
                self.covering_algorithm == "weighted"):
            return self.unordered_predict(X)


class CustomRuleLearner(_RuleLearner):
    name = 'Custom rule inducer'
    __returns__ = CustomRuleClassifier

    def __init__(self, preprocessors, base_rules, params):
        super().__init__(preprocessors, base_rules)
        assert params is not None

        # top-level control procedure (rule ordering)
        self.rule_ordering = params["Rule ordering"]

        # top-level control procedure (covering algorithm)
        self.covering_algorithm = params["Covering algorithm"]
        if self.covering_algorithm == "exclusive":
            self.cover_and_remove = self.exclusive_cover_and_remove
        elif self.covering_algorithm == "weighted":
            self.gamma = params["Gamma"]
            self.cover_and_remove = self.weighted_cover_and_remove

        # bottom-level search procedure (search algorithm)
        self.rule_finder.search_algorithm.beam_width = params["Beam width"]

        # bottom-level search procedure (search strategy)
        self.rule_finder.search_strategy.constrain_continuous = True

        # bottom-level search procedure (search heuristics)
        evaluation_measure = params["Evaluation measure"]
        if evaluation_measure == "entropy":
            evaluator = EntropyEvaluator()
        elif evaluation_measure == "laplace":
            evaluator = LaplaceAccuracyEvaluator()
        elif evaluation_measure == "wracc":
            evaluator = WeightedRelativeAccuracyEvaluator()
        self.rule_finder.quality_evaluator = evaluator

        # bottom-level search procedure (over-fitting avoidance heuristics)
        min_rule_cov = params["Minimum rule coverage"]
        max_rule_length = params["Maximum rule length"]
        self.rule_finder.general_validator.min_covered_examples = min_rule_cov
        self.rule_finder.general_validator.max_rule_length = max_rule_length

        # bottom-level search procedure (over-fitting avoidance heuristics)
        default_alpha = params["Default alpha"]
        parent_alpha = params["Parent alpha"]
        self.rule_finder.significance_validator.default_alpha = default_alpha
        self.rule_finder.significance_validator.parent_alpha = parent_alpha

        self.params = params

    def fit(self, X, Y, W=None):
        Y = Y.astype(dtype=int)
        if self.rule_ordering == "ordered":
            rule_list = self.find_rules(
                X, Y, np.copy(W) if W is not None else None,
                None, self.base_rules, self.domain)
            # add the default rule, if required
            if (not rule_list or rule_list and rule_list[-1].length > 0 or
                    self.covering_algorithm == "weighted"):
                default_rule = self.generate_default_rule(X, Y, W, self.domain)
                rule_list.append(default_rule)

        elif self.rule_ordering == "unordered":
            rule_list = []
            for curr_class in range(len(self.domain.class_var.values)):
                rule_list.extend(self.find_rules(X, Y, W, curr_class,
                                                 self.base_rules, self.domain))
            # add the default rule
            rule_list.append(self.generate_default_rule(X, Y, W, self.domain))

        return CustomRuleClassifier(domain=self.domain, rule_list=rule_list,
                                    params=self.params)


class OWRuleLearner(OWBaseLearner):
    name = "Rule Induction"
    description = "Induce rules from data."
    icon = ""
    priority = 19

    want_main_area = False
    resizing_enabled = False
    auto_apply = Setting(False)

    LEARNER = CustomRuleLearner

    storage_orders = ["ordered", "unordered"]
    storage_covers = ["exclusive", "weighted"]
    storage_measures = ["entropy", "laplace", "wracc"]

    # default parameter values
    learner_name = Setting("CN2 rule inducer")
    rule_ordering = Setting(0)
    covering_algorithm = Setting(0)
    gamma = Setting(0.7)
    evaluation_measure = Setting(0)
    beam_width = Setting(5)
    min_covered_examples = Setting(1)
    max_rule_length = Setting(5)
    default_alpha = Setting(1.0)
    parent_alpha = Setting(1.0)
    checked_default_alpha = Setting(False)
    checked_parent_alpha = Setting(False)

    # actual widget elements
    base_rules = None
    gamma_spin = None

    def add_main_layout(self):
        # top-level control procedure
        top_box = gui.hBox(widget=self.controlArea, box=None, addSpace=2)

        rule_ordering_box = gui.hBox(widget=top_box, box="Rule ordering")
        rule_ordering_rbs = gui.radioButtons(
            widget=rule_ordering_box, master=self, value="rule_ordering",
            callback=self.settings_changed, btnLabels=("Ordered", "Unordered"))
        rule_ordering_rbs.layout().setSpacing(7)

        covering_algorithm_box = gui.hBox(
            widget=top_box, box="Covering algorithm")
        covering_algorithm_rbs = gui.radioButtons(
            widget=covering_algorithm_box, master=self,
            value="covering_algorithm",
            callback=self.settings_changed,
            btnLabels=("Exclusive", "Weighted"))
        covering_algorithm_rbs.layout().setSpacing(7)

        insert_gamma_box = gui.vBox(widget=covering_algorithm_box, box=None)
        gui.separator(insert_gamma_box, 0, 14)
        self.gamma_spin = gui.doubleSpin(
            widget=insert_gamma_box, master=self, value="gamma", minv=0.0,
            maxv=1.0, step=0.01, label="γ:", orientation=Qt.Horizontal,
            callback=self.settings_changed, alignment=Qt.AlignRight,
            enabled=self.storage_covers[self.covering_algorithm] == "weighted")

        # bottom-level search procedure (search bias)
        middle_box = gui.vBox(widget=self.controlArea, box="Rule search")

        evaluation_measure_box = gui.comboBox(
            widget=middle_box, master=self, value="evaluation_measure",
            label="Evaluation measure:", orientation=Qt.Horizontal,
            items=("Entropy", "Laplace accuracy", "WRAcc"),
            callback=self.settings_changed, contentsLength=3)

        beam_width_box = gui.spin(
            widget=middle_box, master=self, value="beam_width", minv=1,
            maxv=100, step=1, label="Beam width:", orientation=Qt.Horizontal,
            callback=self.settings_changed, alignment=Qt.AlignRight,
            controlWidth=80)

        # bottom-level search procedure (over-fitting avoidance bias)
        bottom_box = gui.vBox(widget=self.controlArea, box="Rule filtering")

        min_covered_examples_box = gui.spin(
            widget=bottom_box, master=self, value="min_covered_examples", minv=1,
            maxv=10000, step=1, label="Minimum rule coverage:",
            orientation=Qt.Horizontal, callback=self.settings_changed,
            alignment=Qt.AlignRight, controlWidth=80)

        max_rule_length_box = gui.spin(
            widget=bottom_box, master=self, value="max_rule_length",
            minv=1, maxv=100, step=1, label="Maximum rule length:",
            orientation=Qt.Horizontal, callback=self.settings_changed,
            alignment=Qt.AlignRight, controlWidth=80)

        default_alpha_spin = gui.doubleSpin(
            widget=bottom_box, master=self, value="default_alpha", minv=0.0,
            maxv=1.0, step=0.01, label="Statistical significance\n(default α):",
            orientation=Qt.Horizontal, callback=self.settings_changed,
            alignment=Qt.AlignRight, controlWidth=80,
            checked="checked_default_alpha")

        parent_alpha_spin = gui.doubleSpin(
            widget=bottom_box, master=self, value="parent_alpha", minv=0.0,
            maxv=1.0, step=0.01, label="Relative significance\n(parent α):",
            orientation=Qt.Horizontal, callback=self.settings_changed,
            alignment=Qt.AlignRight, controlWidth=80,
            checked="checked_parent_alpha")

    def settings_changed(self, *args, **kwargs):
        self.gamma_spin.setDisabled(
            self.storage_covers[self.covering_algorithm] != "weighted")
        super().settings_changed(*args, **kwargs)

    def create_learner(self):
        return self.LEARNER(
            preprocessors=self.preprocessors,
            base_rules=self.base_rules,
            params=self.get_learner_parameters()
        )

    def get_learner_parameters(self):
        return OrderedDict([
            ("Rule ordering", self.storage_orders[self.rule_ordering]),
            ("Covering algorithm", self.storage_covers[self.covering_algorithm]),
            ("Gamma", self.gamma),
            ("Evaluation measure", self.storage_measures[self.evaluation_measure]),
            ("Beam width", self.beam_width),
            ("Minimum rule coverage", self.min_covered_examples),
            ("Maximum rule length", self.max_rule_length),
            ("Default alpha", (1.0 if not self.checked_default_alpha
                               else self.default_alpha)),
            ("Parent alpha", (1.0 if not self.checked_parent_alpha
                              else self.parent_alpha))
        ])

if __name__ == "__main__":
    import sys
    from PyQt4.QtGui import QApplication

    a = QApplication(sys.argv)
    ow = OWRuleLearner()
    d = Table('iris')
    ow.set_data(d)
    ow.show()
    a.exec_()
    ow.saveSettings()
