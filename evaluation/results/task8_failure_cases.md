# Task 8: Failure Case Catalog

This file documents failure cases and weaknesses found in the current evaluation results.

## Case 1: Irrelevant papers in retrieval results

**Question:**  
How can businesses reduce the risk of AI giving users incorrect information? (Q08)

**Retrieved Evidence:**  
In the `lance-combined` top 5, two papers were explicitly labelled as not relevant:
- `2610.02281v1` - *The AI Risk Observatory*
- `2609.39518v1` - *Referential Uncertainty in Human--AI Collaboration*

**Generated Answer:**  
The pipeline still generated a research summary using the retrieved papers.

**Failure Type:**  
Retrieval relevance

**What Went Wrong:**  
Some papers in the top 5 were not relevant enough to the question.

**Likely Cause:**  
The query is broad, so the retriever can match general AI-risk or human-AI topics instead of papers directly about incorrect AI answers.

**Suggested Improvement:**  
Use stronger query rewriting or reranking so papers directly related to hallucinations, reliability, and error reduction rank higher.


## Case 2: Correct paper found, but irrelevant paper also ranked highly

**Question:**  
How much can the choice of simulated user change the results of an AI agent benchmark, and what mistake do simulated users make most often? (Q10)

**Retrieved Evidence:**  
The correct paper `2609.38043v1` was ranked first, but `2609.38652v1` (*AgBench*) was ranked third by `lance-combined` and was labelled 0, or not relevant.

**Generated Answer:**  
The generated summary correctly focused on `UserProxyBench` and reported the main findings from the correct paper.

**Failure Type:**  
Noisy retrieval

**What Went Wrong:**  
The correct paper was found, but an unrelated benchmark paper still appeared high in the top 5.

**Likely Cause:**  
The papers share similar terms such as "agent", "benchmark", and "evaluation", which can make a less relevant paper look similar during retrieval.

**Suggested Improvement:**  
Improve reranking so papers matching the full meaning of the question are prioritized over papers that only share broad keywords.


## Case 3: Retrieval changes when the question wording changes

**Question:**  
Can an AI model's step-by-step reasoning be trusted?

**Retrieved Evidence:**  
The retriever comparison report says that this shorter wording returned papers about general trust, robots, and human-AI trust across the retrievers. The longer benchmark wording for Q11 retrieved the expected reasoning-trace paper.

**Generated Answer:**  
N/A - this issue was identified during retrieval testing before answer generation.

**Failure Type:**  
Query wording sensitivity

**What Went Wrong:**  
Small changes in wording changed which papers were retrieved.

**Likely Cause:**  
The embedding model can interpret the word "trusted" too broadly instead of focusing on chain-of-thought or reasoning-trace faithfulness.

**Suggested Improvement:**  
Use the query rewriter before retrieval and consider testing a stronger embedding model.


## Case 4: Expected-paper benchmark does not match the newer corpus

**Questions:**  
- Q14: How can a company estimate how confident an AI model is in its own answer?
- Q15: How can the memory and compute cost of running long-context language models be reduced without losing accuracy?

**Retrieved Evidence:**  
The expected Q14 paper ranked 8th, while the expected Q15 papers ranked 21st and 22nd in `lance-combined`. The comparison report notes that the papers ranked above them were still on-topic. It also notes that the expected papers were selected from an older 1,220-paper corpus, while the current corpus contains about 3,150 papers.

**Generated Answer:**  
The end-to-end pipeline still produced on-topic summaries using newer retrieved papers.

**Failure Type:**  
Evaluation / benchmark answer-key gap

**What Went Wrong:**  
The benchmark marks retrieval as a miss even when newer, relevant papers rank above the originally expected papers.

**Likely Cause:**  
The benchmark answer key was created before the research corpus grew.

**Suggested Improvement:**  
Update the benchmark so each question can accept multiple relevant papers, and periodically review the expected-paper list as the corpus changes.


## Case 5: Reference-list chunks can rank too highly

**Question:**  
General retrieval issue observed during testing.

**Retrieved Evidence:**  
The retriever comparison report notes that bibliography/reference-list chunks are indexed and can sometimes rank highly.

**Generated Answer:**  
N/A - this is a retrieval-stage issue.

**Failure Type:**  
Chunk quality / retrieval noise

**What Went Wrong:**  
Reference-list text can be retrieved even though it does not contain the actual research evidence needed to answer the question.

**Likely Cause:**  
The chunking/indexing pipeline includes bibliography sections along with useful paper content.

**Suggested Improvement:**  
Filter out bibliography/reference sections during chunking or give those sections a much lower retrieval weight.


## Summary

The main weaknesses found were:
- irrelevant papers appearing in the top 5,
- retrieval being sensitive to question wording,
- benchmark expected-paper lists becoming outdated as the corpus grows,
- and reference-list chunks adding retrieval noise.

These cases can be used to guide future improvements to query rewriting, reranking, benchmark maintenance, and chunk filtering.
