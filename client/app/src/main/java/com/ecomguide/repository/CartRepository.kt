package com.ecomguide.repository

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.CartItem

/** Singleton in-memory cart state shared across all screens. */
object CartRepository {

    private val _items = MutableLiveData<MutableList<CartItem>>(mutableListOf())
    val items: LiveData<MutableList<CartItem>> = _items

    val badgeCount: LiveData<Int> get() = _badgeCount
    private val _badgeCount = MutableLiveData(0)

    fun add(product: ApiProduct, skuLabel: String = "", qty: Int = 1) {
        val current = _items.value?.toMutableList() ?: mutableListOf()
        val idx = current.indexOfFirst { it.productId == product.resolvedId }
        if (idx != -1) {
            // 用 copy() 创建新对象，让 DiffUtil 能检测到变化
            current[idx] = current[idx].copy(qty = current[idx].qty + qty)
        } else {
            current.add(
                CartItem(
                    productId = product.resolvedId,
                    title = product.resolvedTitle,
                    price = product.resolvedPrice,
                    imageUrl = product.resolvedImageUrl,
                    skuLabel = skuLabel.ifBlank { product.skus.firstOrNull()?.label ?: "" },
                    qty = qty
                )
            )
        }
        _items.value = current
        _badgeCount.value = current.sumOf { it.qty }
    }

    fun remove(productId: String) {
        val current = _items.value?.toMutableList() ?: return
        current.removeAll { it.productId == productId }
        _items.value = current
        _badgeCount.value = current.sumOf { it.qty }
    }

    fun updateQty(productId: String, delta: Int) {
        val current = _items.value?.toMutableList() ?: return
        val idx = current.indexOfFirst { it.productId == productId }
        if (idx == -1) return
        val newQty = (current[idx].qty + delta).coerceAtLeast(0)
        if (newQty == 0) {
            current.removeAt(idx)
        } else {
            // copy() 生成新对象，DiffUtil 的 areContentsTheSame 才能检测到 qty 变化
            current[idx] = current[idx].copy(qty = newQty)
        }
        _items.value = current
        _badgeCount.value = current.sumOf { it.qty }
    }

    fun clear() {
        _items.value = mutableListOf()
        _badgeCount.value = 0
    }

    fun total(): Double = _items.value?.sumOf { it.price * it.qty } ?: 0.0
    fun count(): Int = _items.value?.sumOf { it.qty } ?: 0
}
