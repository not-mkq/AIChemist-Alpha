from db import get_connection

def run():
    conn = get_connection()
    cur = conn.cursor()
    # 插入一个项目
    cur.execute("INSERT OR IGNORE INTO projects (name) VALUES ('v2_test_project')")
    cur.execute("INSERT OR IGNORE INTO batches (project_name, name, upload_type) VALUES ('v2_test_project', 'B1', 'item')")
    cur.execute("INSERT OR IGNORE INTO items (project_name, batch_name, name) VALUES ('v2_test_project', 'B1', 'I1')")
    # 注册文件
    cur.execute("""
        INSERT OR REPLACE INTO files (project_name, batch_name, item_name, filename, rel_path)
        VALUES ('v2_test_project', 'B1', 'I1', 'LSV-1.txt', 'data/LSV-1.txt')
    """)
    # 打上标签
    cur.execute("INSERT OR REPLACE INTO file_labels (project_name, batch_name, item_name, filename, label) VALUES ('v2_test_project', 'B1', 'I1', 'LSV-1.txt', 'LSV-1')")
    conn.commit()
    conn.close()
    print("✅ 测试数据库注入完成")

if __name__ == "__main__":
    run()