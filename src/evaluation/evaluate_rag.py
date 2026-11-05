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


if __name__ == "__main__":
    print("--- Testing RAGAS Evaluation Module ---")
    
    # Dummy test case to verify pipeline workflow without failing on missing keys
    sample_test_cases = [
        {
            "question": "What are the financial risks in AI adoption?",
            "contexts": ["AI adoption involves operational uncertainty, high compute costs, and regulatory compliance risks."],
            "answer": "Financial risks include high computational costs, uncertain ROI, and potential compliance fines.",
            "ground_truth": "Key financial risks include compute expenditures, regulatory non-compliance costs, and unpredictable ROI."
        }
    ]

    try:
        res = run_ragas_benchmark(sample_test_cases)
        print("Evaluation finished successfully!")
        print(res)
    except Exception as e:
        print(f"Error during evaluation execution: {e}")
