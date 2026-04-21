#!/bin/bash
cd ~/buddy-buddy-tools

echo "================================"
echo "  在庫管理表 + 発送管理表 更新"
echo "================================"
echo ""

echo "【1/2】在庫管理表を更新中..."
python3 update.py
echo ""

echo "【2/2】発送管理表を更新中..."
python3 update_shipping.py
echo ""

echo "================================"
echo "  すべて完了しました！"
echo "================================"
echo ""
echo "Enterキーで閉じる..."
read
