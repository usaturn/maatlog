Code
====

caption なしコード（外形 = ``.highlight-*`` div）。

.. code-block:: python

   print("hello")

caption 付きコード（外形 = ``.literal-block-wrapper``。caption を含む）。

.. code-block:: python
   :caption: sample.py の抜粋

   print("captioned")

行番号付きコード（``table.highlighttable`` は外形の内側。通常の表と混同しない）。

.. code-block:: python
   :linenos:

   print("line 1")
   print("line 2")

literalinclude（caption + 行番号 + 長い行）。

.. literalinclude:: _code/sample.py
   :language: python
   :caption: sample.py
   :linenos:

長い行を含むコード（外形内部で横スクロールし、document は溢れない）。

.. code-block:: python

   value = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

parsed-literal（非ハイライト経路の回帰）。

.. parsed-literal::

   plain *emphasized* text
