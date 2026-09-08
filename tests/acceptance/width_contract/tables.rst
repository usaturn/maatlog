Tables
======

短い list-table（AC1 の基準。罫線が表の右端まで届くこと）。

.. list-table::
   :header-rows: 1

   * - 列A
     - 列B
     - 列C
   * - a1
     - b1
     - c1
   * - a2
     - b2
     - c2

幅広表（16 列。th の white-space: nowrap により最小幅が main を超え、
全 CONTRACT_VIEWPORTS で wrapper の横スクロールが発生する）。

.. list-table::
   :header-rows: 1

   * - Column 01
     - Column 02
     - Column 03
     - Column 04
     - Column 05
     - Column 06
     - Column 07
     - Column 08
     - Column 09
     - Column 10
     - Column 11
     - Column 12
     - Column 13
     - Column 14
     - Column 15
     - Column 16
   * - d1
     - d2
     - d3
     - d4
     - d5
     - d6
     - d7
     - d8
     - d9
     - d10
     - d11
     - d12
     - d13
     - d14
     - d15
     - d16

rowspan / colspan を持つ grid 表（意図した罫線の欠けは不具合扱いにしない）。

+------------------------+---------------------+
| Header 1               | Header 2            |
+========================+=====================+
| Spans two rows         | row 1, column 2     |
+                        +---------------------+
|                        | row 2, column 2     |
+------------------------+---------------------+
| Spans two columns                            |
+------------------------+---------------------+

caption・名前・列幅・配置を持つ表。

.. table:: 惑星一覧
   :name: tbl-planets
   :widths: 30 70
   :align: center

   ========  =====================
   Planet    Description
   ========  =====================
   Earth     Our home
   Mars      The red one
   ========  =====================

csv-table。

.. csv-table:: CSV 一覧
   :header: "名前", "値"

   "alpha", "1"
   "beta", "2"

入れ子の表（セル内に list-table。wrapper は重複生成せず各表に 1 つ）。

.. list-table::
   :header-rows: 1

   * - 項目
     - 内容
   * - outer
     - .. list-table::
          :class: nested-inner

          * - inner-a
            - inner-b

名前付き表への参照: :ref:`tbl-planets` / :numref:`tbl-planets`。
