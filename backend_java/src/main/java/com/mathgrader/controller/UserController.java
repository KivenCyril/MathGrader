package com.mathgrader.controller;

import com.mathgrader.model.UserDTO;
import com.mathgrader.service.UserService;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.web.PageableDefault;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/admin/users")
@PreAuthorize("hasRole('ADMIN')")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping
    public Page<UserDTO> list(@PageableDefault(size = 10) Pageable pageable) {
        return userService.findAll(pageable);
    }

    @PostMapping
    public UserDTO create(@RequestBody UserDTO dto) {
        return userService.create(dto);
    }

    @PutMapping("/{id}")
    public UserDTO update(@PathVariable Long id, @RequestBody UserDTO dto) {
        return userService.update(id, dto);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable Long id) {
        userService.delete(id);
        return ResponseEntity.ok().build();
    }
}
