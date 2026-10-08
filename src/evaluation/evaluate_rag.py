import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, faithfulness, context_recall

def run_ragas_benchmark(test_cases: list, output_report_path: str = "data/ragas_evaluation.csv"):
    df = pd.DataFrame(test_cases)
    dataset = Dataset.from_pandas(df)

    results = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_recall]
    )

    results_df = results.to_pandas()
    results_df.to_csv(output_report_path, index=False)
    return results
