from RAG_main import RAGRetriever

# 初始化
print("正在初始化检索器...")
retriever = RAGRetriever()
print("初始化完成！\n")

# 测试检索
query = "折线图？"
print(f"查询: {query}\n")

docs = retriever.retrieve(query)

print(f"找到 {len(docs)} 个相关文档:\n")
for i, doc in enumerate(docs, 1):
    print(f"【文档 {i}】")
    print(f"来源: {doc.metadata.get('source', '未知')}")
    print(f"内容:\n{doc.page_content}\n")
    print("-" * 80)
