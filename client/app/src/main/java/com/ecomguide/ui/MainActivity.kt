package com.ecomguide.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.GravityCompat
import com.ecomguide.R
import com.ecomguide.databinding.ActivityMainBinding
import com.ecomguide.repository.CartRepository
import com.ecomguide.ui.cart.CartActivity
import com.ecomguide.ui.chat.ChatViewModel
import com.ecomguide.ui.sidebar.ChatHistoryActivity
import com.ecomguide.ui.sidebar.MessagesActivity
import com.ecomguide.ui.sidebar.MyOrdersActivity

class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private val chatVm: ChatViewModel by viewModels()

    /** 从历史对话页返回时，如果用户选了某条对话则恢复它 */
    private val historyLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val topic = result.data?.getStringExtra("load_history") ?: return@registerForActivityResult
            chatVm.resetChat()
            chatVm.sendMessage("我想重新看看：$topic")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)

        setupDrawer()
        setupToolbarActions()
        setupBackPressedHandling()
        observeCart()
    }

    private fun setupDrawer() {
        b.btnMenu.setOnClickListener {
            if (b.drawerLayout.isDrawerOpen(GravityCompat.START))
                b.drawerLayout.closeDrawer(GravityCompat.START)
            else
                b.drawerLayout.openDrawer(GravityCompat.START)
        }

        b.navigationView.setNavigationItemSelectedListener { item ->
            b.drawerLayout.closeDrawer(GravityCompat.START)
            when (item.itemId) {
                R.id.nav_history  -> historyLauncher.launch(Intent(this, ChatHistoryActivity::class.java))
                R.id.nav_orders   -> startActivity(Intent(this, MyOrdersActivity::class.java))
                R.id.nav_messages -> startActivity(Intent(this, MessagesActivity::class.java))
                R.id.nav_cart     -> startActivity(Intent(this, CartActivity::class.java))
                R.id.nav_favorites -> Toast.makeText(this, "收藏功能即将上线", Toast.LENGTH_SHORT).show()
            }
            true
        }
    }

    private fun setupToolbarActions() {
        b.btnNewChat.setOnClickListener { chatVm.resetChat() }
        b.btnCart.setOnClickListener { startActivity(Intent(this, CartActivity::class.java)) }
    }

    private fun observeCart() {
        CartRepository.badgeCount.observe(this) { count ->
            b.tvCartBadge.visibility = if (count > 0) View.VISIBLE else View.GONE
            b.tvCartBadge.text = if (count > 9) "9+" else count.toString()
        }
    }

    private fun setupBackPressedHandling() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (b.drawerLayout.isDrawerOpen(GravityCompat.START)) {
                    b.drawerLayout.closeDrawer(GravityCompat.START)
                    return
                }
                // 让系统继续分发返回事件，避免回调自身递归触发。
                isEnabled = false
                onBackPressedDispatcher.onBackPressed()
                isEnabled = true
            }
        })
    }
}
